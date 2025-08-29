"""
Система аутентификации WebSocket подключений
"""

import os
import time
from typing import Dict, Optional, Set
from pathlib import Path

from config.websocket_config import WEBSOCKET_CONFIG
from src.utils.logger import get_component_logger

logger = get_component_logger("websocket_auth")


class WebSocketAuthenticator:
    """Аутентификация WebSocket подключений"""
    
    def __init__(self):
        self.logger = logger
        
        # Загружаем приватный токен
        self.private_token = os.getenv("WEBSOCKET_PRIVATE_TOKEN") or WEBSOCKET_CONFIG["private_token"]
        
        # Загружаем VIP ключи
        self.vip_keys: Set[str] = self._load_vip_keys()
        
        # Rate limiting для публичного доступа
        self.rate_limits: Dict[str, list] = {}  # IP -> список временных меток запросов
        
        # Статистика
        self.connection_count = {"private": 0, "vip": 0, "public": 0}
        
    def _load_vip_keys(self) -> Set[str]:
        """Загрузка VIP ключей из файла"""
        vip_file = Path(WEBSOCKET_CONFIG.get("vip_keys_file", "config/vip_keys.txt"))
        
        if not vip_file.exists():
            self.logger.warning("VIP keys file not found", file=str(vip_file))
            return set()
        
        try:
            with open(vip_file, 'r', encoding='utf-8') as f:
                keys = {line.strip() for line in f.readlines() if line.strip()}
            
            self.logger.info("Loaded VIP keys", count=len(keys))
            return keys
            
        except Exception as e:
            self.logger.error("Error loading VIP keys", file=str(vip_file), error=str(e))
            return set()
    
    def authenticate(self, path: str, query_params: Dict[str, str], headers: Dict[str, str], 
                    client_ip: str) -> Dict[str, any]:
        """
        Аутентификация WebSocket подключения
        
        Args:
            path: Путь WebSocket подключения
            query_params: Query параметры
            headers: HTTP заголовки
            client_ip: IP адрес клиента
            
        Returns:
            Словарь с информацией об уровне доступа и ограничениях
        """
        try:
            # Определяем тип подключения по пути
            if path.startswith("/private"):
                return self._authenticate_private(query_params)
            
            elif path.startswith("/vip"):
                return self._authenticate_vip(query_params)
            
            elif path.startswith("/public"):
                return self._authenticate_public(client_ip)
            
            else:
                return {"access_level": "denied", "reason": "Invalid endpoint"}
                
        except Exception as e:
            self.logger.error("Authentication error", 
                             path=path, client_ip=client_ip, error=str(e))
            return {"access_level": "denied", "reason": "Authentication failed"}
    
    def _authenticate_private(self, query_params: Dict[str, str]) -> Dict[str, any]:
        """Аутентификация приватного доступа"""
        token = query_params.get("token")
        
        if not token:
            return {"access_level": "denied", "reason": "Token required"}
        
        if token == self.private_token:
            self.connection_count["private"] += 1
            
            return {
                "access_level": "private",
                "rate_limit": None,  # Без ограничений
                "data_delay": WEBSOCKET_CONFIG["data_delays"]["private"],
                "access_filters": WEBSOCKET_CONFIG["access_filters"]["private"],
                "compression": True
            }
        
        return {"access_level": "denied", "reason": "Invalid token"}
    
    def _authenticate_vip(self, query_params: Dict[str, str]) -> Dict[str, any]:
        """Аутентификация VIP доступа"""
        key = query_params.get("key")
        
        if not key:
            return {"access_level": "denied", "reason": "VIP key required"}
        
        if key in self.vip_keys:
            self.connection_count["vip"] += 1
            
            return {
                "access_level": "vip",
                "rate_limit": None,  # Без ограничений для VIP
                "data_delay": WEBSOCKET_CONFIG["data_delays"]["vip"],
                "access_filters": WEBSOCKET_CONFIG["access_filters"]["vip"],
                "compression": True
            }
        
        return {"access_level": "denied", "reason": "Invalid VIP key"}
    
    def _authenticate_public(self, client_ip: str) -> Dict[str, any]:
        """Аутентификация публичного доступа с rate limiting"""
        # Проверяем rate limit
        if not self._check_rate_limit(client_ip):
            return {"access_level": "denied", "reason": "Rate limit exceeded"}
        
        self.connection_count["public"] += 1
        
        return {
            "access_level": "public",
            "rate_limit": WEBSOCKET_CONFIG["public_rate_limit"],
            "data_delay": WEBSOCKET_CONFIG["data_delays"]["public"],
            "access_filters": WEBSOCKET_CONFIG["access_filters"]["public"],
            "compression": False
        }
    
    def _check_rate_limit(self, client_ip: str) -> bool:
        """Проверка rate limit для публичного доступа"""
        now = time.time()
        rate_config = WEBSOCKET_CONFIG["public_rate_limit"]
        
        requests_per_second = rate_config["requests_per_second"]
        burst_size = rate_config["burst_size"]
        
        # Инициализируем список запросов для IP
        if client_ip not in self.rate_limits:
            self.rate_limits[client_ip] = []
        
        # Очищаем старые запросы (старше 1 секунды)
        self.rate_limits[client_ip] = [
            timestamp for timestamp in self.rate_limits[client_ip]
            if now - timestamp < 1.0
        ]
        
        # Проверяем лимит
        if len(self.rate_limits[client_ip]) >= burst_size:
            self.logger.warning("Rate limit exceeded", client_ip=client_ip)
            return False
        
        # Добавляем текущий запрос
        self.rate_limits[client_ip].append(now)
        return True
    
    def cleanup_rate_limits(self):
        """Периодическая очистка старых записей rate limit"""
        now = time.time()
        cleanup_interval = WEBSOCKET_CONFIG["public_rate_limit"]["cleanup_interval"]
        
        for client_ip in list(self.rate_limits.keys()):
            # Удаляем записи старше cleanup_interval
            self.rate_limits[client_ip] = [
                timestamp for timestamp in self.rate_limits[client_ip]
                if now - timestamp < cleanup_interval
            ]
            
            # Удаляем пустые записи
            if not self.rate_limits[client_ip]:
                del self.rate_limits[client_ip]
    
    def add_vip_key(self, key: str):
        """Добавить VIP ключ во время работы"""
        self.vip_keys.add(key)
        self.logger.info("VIP key added", key=key[:8] + "...")
    
    def remove_vip_key(self, key: str):
        """Удалить VIP ключ"""
        self.vip_keys.discard(key)
        self.logger.info("VIP key removed", key=key[:8] + "...")
    
    def get_stats(self) -> Dict:
        """Статистика аутентификации"""
        active_ips = len(self.rate_limits)
        total_connections = sum(self.connection_count.values())
        
        return {
            "total_connections": total_connections,
            "connection_types": self.connection_count.copy(),
            "active_rate_limited_ips": active_ips,
            "vip_keys_count": len(self.vip_keys),
            "private_token_configured": bool(self.private_token)
        }
