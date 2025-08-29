"""
Система рассылки данных через WebSocket
"""

import asyncio
import json
import time
from typing import Dict, List, Set, Optional
from datetime import datetime, timezone

from src.utils.logger import get_component_logger

logger = get_component_logger("websocket_broadcaster")


class WebSocketBroadcaster:
    """Рассылка данных через WebSocket с учетом уровней доступа"""
    
    def __init__(self):
        self.logger = logger
        
        # Подключения по типам доступа
        self.connections = {
            "private": set(),
            "vip": set(),
            "public": set()
        }
        
        # Буферы данных для разных типов доступа
        self.data_buffers = {
            "private": [],
            "vip": [],
            "public": []
        }
        
        # Статистика
        self.messages_sent = 0
        self.total_data_sent = 0
        self.last_broadcast_time = None
        
        # Задача периодической очистки
        self.cleanup_task = None
        self.is_running = False
    
    def start(self):
        """Запуск broadcaster"""
        if self.is_running:
            return
        
        self.is_running = True
        
        # Запускаем задачу периодической очистки соединений
        self.cleanup_task = asyncio.create_task(self._cleanup_connections())
        
        self.logger.info("WebSocket broadcaster started")
    
    async def stop(self):
        """Остановка broadcaster"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        
        # Закрываем все соединения
        await self._close_all_connections()
        
        self.logger.info("WebSocket broadcaster stopped")
    
    def add_connection(self, websocket, access_level: str, connection_info: Dict):
        """Добавить WebSocket соединение"""
        if access_level in self.connections:
            self.connections[access_level].add(websocket)
            
            # Добавляем метаданные к соединению
            websocket._auth_info = connection_info
            websocket._access_level = access_level
            websocket._connected_at = time.time()
            
            self.logger.info("Connection added", 
                           access_level=access_level,
                           total_connections=len(self.connections[access_level]))
    
    def remove_connection(self, websocket):
        """Удалить WebSocket соединение"""
        for access_level, connections in self.connections.items():
            if websocket in connections:
                connections.discard(websocket)
                
                self.logger.info("Connection removed",
                               access_level=access_level,
                               remaining_connections=len(connections))
                break
    
    async def broadcast_hot_pool_update(self, hot_pool_data: Dict):
        """Рассылка обновлений горячего пула"""
        try:
            # Базовые данные для всех типов доступа
            timestamp = datetime.now(timezone.utc).isoformat()
            
            # Приватный канал - полные данные без задержек
            if self.connections["private"]:
                private_data = {
                    "type": "hot_pool_update",
                    "timestamp": timestamp,
                    "data": hot_pool_data,
                    "access_level": "private"
                }
                await self._send_to_connections("private", private_data)
            
            # VIP канал - расширенные данные без задержек
            if self.connections["vip"]:
                vip_data = self._filter_data_for_vip(hot_pool_data)
                vip_message = {
                    "type": "hot_pool_update", 
                    "timestamp": timestamp,
                    "data": vip_data,
                    "access_level": "vip"
                }
                await self._send_to_connections("vip", vip_message)
            
            # Публичный канал - только diamond категория с задержкой
            if self.connections["public"]:
                public_data = self._filter_data_for_public(hot_pool_data)
                public_message = {
                    "type": "hot_pool_update",
                    "timestamp": timestamp,
                    "data": public_data,
                    "access_level": "public",
                    "disclaimer": "Limited public feed. Upgrade for full access."
                }
                
                # Задержка для публичного доступа
                from config.websocket_config import WEBSOCKET_CONFIG
                delay = WEBSOCKET_CONFIG["data_delays"]["public"]
                
                if delay > 0:
                    await asyncio.sleep(delay)
                
                await self._send_to_connections("public", public_message)
            
            self.last_broadcast_time = time.time()
            
        except Exception as e:
            self.logger.error("Error broadcasting hot pool update", error=str(e))
    
    def _filter_data_for_vip(self, full_data: Dict) -> Dict:
        """Фильтрация данных для VIP доступа"""
        # VIP получает все кроме внутренней аналитики
        filtered_data = full_data.copy()
        
        # Удаляем внутренние метрики если есть
        if "internal_metrics" in filtered_data:
            del filtered_data["internal_metrics"]
        
        return filtered_data
    
    def _filter_data_for_public(self, full_data: Dict) -> Dict:
        """Фильтрация данных для публичного доступа - только diamond категория"""
        orders = full_data.get("orders", [])
        
        # Фильтруем только diamond ордера
        diamond_orders = []
        for order in orders:
            categories = order.get("categories", {})
            if categories.get("recommended") == "diamond":
                # Упрощенная структура для публичного доступа
                public_order = {
                    "symbol": order["symbol"],
                    "exchange": order.get("exchange", "binance"),
                    "usd_value": order["usd_value"],
                    "lifetime_seconds": order["lifetime_seconds"],
                    "category": "diamond",
                    "weight": order.get("weights", {}).get("recommended", 0)
                }
                diamond_orders.append(public_order)
        
        return {
            "timestamp": full_data.get("timestamp"),
            "total_diamond_orders": len(diamond_orders),
            "diamond_orders": diamond_orders,
            "market_temperature": self._calculate_public_market_temp(full_data)
        }
    
    def _calculate_public_market_temp(self, data: Dict) -> str:
        """Рассчитать температуру рынка для публичного доступа"""
        total_orders = data.get("total_orders", 0)
        
        if total_orders >= 50:
            return "extreme"
        elif total_orders >= 20:
            return "hot"
        elif total_orders >= 10:
            return "warm"
        else:
            return "cold"
    
    async def _send_to_connections(self, access_level: str, data: Dict):
        """Отправка данных всем соединениям определенного уровня"""
        connections = self.connections.get(access_level, set())
        
        if not connections:
            return
        
        message = json.dumps(data, ensure_ascii=False)
        message_size = len(message.encode('utf-8'))
        
        # Отправляем всем активным соединениям
        disconnected = set()
        
        for websocket in connections.copy():
            try:
                await websocket.send(message)
                self.messages_sent += 1
                self.total_data_sent += message_size
                
            except Exception as e:
                self.logger.warning("Failed to send message to connection",
                                   access_level=access_level, error=str(e))
                disconnected.add(websocket)
        
        # Удаляем отключенные соединения
        for websocket in disconnected:
            connections.discard(websocket)
        
        if disconnected:
            self.logger.info("Cleaned up disconnected connections",
                           access_level=access_level,
                           removed=len(disconnected),
                           remaining=len(connections))
    
    async def broadcast_system_stats(self, stats: Dict):
        """Рассылка системной статистики (только для private/vip)"""
        timestamp = datetime.now(timezone.utc).isoformat()
        
        message = {
            "type": "system_stats",
            "timestamp": timestamp,
            "stats": stats
        }
        
        # Отправляем только private и vip
        await self._send_to_connections("private", message)
        await self._send_to_connections("vip", message)
    
    async def _cleanup_connections(self):
        """Периодическая задача очистки соединений"""
        while self.is_running:
            try:
                # Проверка активности соединений через ping
                await self._ping_all_connections()
                
            except Exception as e:
                self.logger.error("Error in cleanup task", error=str(e))
            
            await asyncio.sleep(30)  # Очистка каждые 30 секунд
    
    async def _ping_all_connections(self):
        """Ping всех соединений для проверки активности"""
        from config.websocket_config import WEBSOCKET_CONFIG
        
        for access_level, connections in self.connections.items():
            for websocket in connections.copy():
                try:
                    await asyncio.wait_for(
                        websocket.ping(),
                        timeout=WEBSOCKET_CONFIG.get("ping_timeout", 10)
                    )
                except Exception:
                    # Соединение не отвечает - удаляем
                    connections.discard(websocket)
    
    async def _close_all_connections(self):
        """Закрытие всех соединений"""
        for access_level, connections in self.connections.items():
            for websocket in connections.copy():
                try:
                    await websocket.close()
                except Exception:
                    pass
            connections.clear()
    
    def get_stats(self) -> Dict:
        """Статистика broadcaster"""
        total_connections = sum(len(conns) for conns in self.connections.values())
        
        return {
            "is_running": self.is_running,
            "total_connections": total_connections,
            "connections_by_type": {k: len(v) for k, v in self.connections.items()},
            "messages_sent": self.messages_sent,
            "total_data_sent": self.total_data_sent,
            "last_broadcast": self.last_broadcast_time,
            "rate_limited_ips": len(self.rate_limits)
        }
