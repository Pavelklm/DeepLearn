"""
Основной WebSocket сервер для передачи данных сканнера
"""

import asyncio
import websockets
import json
from typing import Dict, Set, Optional
from urllib.parse import urlparse, parse_qs
from datetime import datetime, timezone

from config.websocket_config import WEBSOCKET_CONFIG
from src.websocket.auth import WebSocketAuthenticator
from src.websocket.broadcaster import WebSocketBroadcaster
from src.utils.logger import get_component_logger

logger = get_component_logger("websocket_server")


class WebSocketServer:
    """
    Основной WebSocket сервер
    """
    
    def __init__(self, host: str = None, port: int = None):
        """
        Инициализация WebSocket сервера
        
        Args:
            host: Хост для привязки (по умолчанию из конфига)
            port: Порт для привязки (по умолчанию из конфига)
        """
        self.logger = logger
        
        self.host = host or WEBSOCKET_CONFIG["host"]
        self.port = port or WEBSOCKET_CONFIG["port"]
        
        # Компоненты
        self.authenticator = WebSocketAuthenticator()
        self.broadcaster = WebSocketBroadcaster()
        
        # Состояние сервера
        self.server = None
        self.is_running = False
        
        # Статистика
        self.connection_attempts = 0
        self.failed_connections = 0
        self.start_time = None
        
        # Очередь данных от сканнера
        self.data_queue = asyncio.Queue()
        self.data_processor_task = None
    
    async def start(self):
        """Запуск WebSocket сервера"""
        if self.is_running:
            self.logger.warning("Server is already running")
            return
        
        try:
            # Запускаем broadcaster
            self.broadcaster.start()
            
            # Запускаем обработчик данных
            self.data_processor_task = asyncio.create_task(self._process_data_queue())
            
            # Запускаем WebSocket сервер
            self.server = await websockets.serve(
                self.handle_connection,
                self.host,
                self.port,
                ping_interval=WEBSOCKET_CONFIG.get("ping_interval", 20),
                ping_timeout=WEBSOCKET_CONFIG.get("ping_timeout", 10),
                close_timeout=WEBSOCKET_CONFIG.get("close_timeout", 10)
            )
            
            self.is_running = True
            self.start_time = datetime.now(timezone.utc)
            
            self.logger.info("WebSocket server started",
                           host=self.host, port=self.port)
            
        except Exception as e:
            self.logger.error("Failed to start WebSocket server", 
                            host=self.host, port=self.port, error=str(e))
            raise
    
    async def stop(self):
        """Остановка WebSocket сервера"""
        if not self.is_running:
            return
        
        self.logger.info("Stopping WebSocket server")
        self.is_running = False
        
        try:
            # Останавливаем обработчик данных
            if self.data_processor_task:
                self.data_processor_task.cancel()
                try:
                    await self.data_processor_task
                except asyncio.CancelledError:
                    pass
            
            # Останавливаем broadcaster
            await self.broadcaster.stop()
            
            # Останавливаем сервер
            if self.server:
                self.server.close()
                await self.server.wait_closed()
            
            self.logger.info("WebSocket server stopped")
            
        except Exception as e:
            self.logger.error("Error stopping WebSocket server", error=str(e))
    
    async def handle_connection(self, websocket, path):
        """Обработка нового WebSocket подключения"""
        self.connection_attempts += 1
        
        try:
            # Получаем информацию о подключении
            client_ip = websocket.remote_address[0] if websocket.remote_address else "unknown"
            
            # Парсим URL и параметры
            parsed_url = urlparse(path)
            query_params = {k: v[0] for k, v in parse_qs(parsed_url.query).items()}
            headers = dict(websocket.request_headers)
            
            self.logger.info("New WebSocket connection attempt",
                           path=path, client_ip=client_ip)
            
            # Аутентификация
            auth_result = self.authenticator.authenticate(
                path=parsed_url.path,
                query_params=query_params,
                headers=headers,
                client_ip=client_ip
            )
            
            if auth_result.get("access_level") == "denied":
                reason = auth_result.get("reason", "Access denied")
                self.logger.warning("Connection denied", 
                                  client_ip=client_ip, reason=reason)
                
                await websocket.close(code=1008, reason=reason)
                self.failed_connections += 1
                return
            
            # Успешная аутентификация
            access_level = auth_result["access_level"]
            
            # Добавляем соединение к broadcaster
            self.broadcaster.add_connection(websocket, access_level, auth_result)
            
            # Отправляем приветственное сообщение
            welcome_message = {
                "type": "welcome",
                "access_level": access_level,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "rate_limit": auth_result.get("rate_limit"),
                "data_delay": auth_result.get("data_delay", 0)
            }
            
            await websocket.send(json.dumps(welcome_message))
            
            self.logger.info("WebSocket connection established",
                           access_level=access_level, client_ip=client_ip)
            
            # Обрабатываем входящие сообщения
            await self._handle_messages(websocket, access_level)
            
        except websockets.exceptions.ConnectionClosed:
            self.logger.info("WebSocket connection closed", client_ip=client_ip)
        except Exception as e:
            self.logger.error("Error handling WebSocket connection",
                            client_ip=client_ip, error=str(e))
            self.failed_connections += 1
        finally:
            # Удаляем соединение из broadcaster
            self.broadcaster.remove_connection(websocket)
    
    async def _handle_messages(self, websocket, access_level: str):
        """Обработка входящих сообщений от клиента"""
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self._process_client_message(websocket, access_level, data)
                    
                except json.JSONDecodeError:
                    error_response = {
                        "type": "error",
                        "message": "Invalid JSON format"
                    }
                    await websocket.send(json.dumps(error_response))
                    
                except Exception as e:
                    self.logger.error("Error processing client message",
                                    access_level=access_level, error=str(e))
                    
        except websockets.exceptions.ConnectionClosed:
            pass
    
    async def _process_client_message(self, websocket, access_level: str, data: Dict):
        """Обработка сообщения от клиента"""
        message_type = data.get("type")
        
        if message_type == "ping":
            # Отвечаем на ping
            pong_response = {
                "type": "pong",
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
            await websocket.send(json.dumps(pong_response))
            
        elif message_type == "subscribe":
            # Подписка на определенные типы данных
            await self._handle_subscription(websocket, access_level, data)
            
        elif message_type == "get_stats" and access_level in ["private", "vip"]:
            # Запрос статистики (только для private/vip)
            stats = await self._get_server_stats()
            stats_response = {
                "type": "stats_response",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "data": stats
            }
            await websocket.send(json.dumps(stats_response))
            
        else:
            # Неизвестный тип сообщения
            error_response = {
                "type": "error",
                "message": f"Unknown message type: {message_type}"
            }
            await websocket.send(json.dumps(error_response))
    
    async def _handle_subscription(self, websocket, access_level: str, data: Dict):
        """Обработка подписки клиента"""
        # В текущей версии все клиенты автоматически подписаны на hot_pool_updates
        # В будущем можно добавить селективные подписки
        
        channels = data.get("channels", ["hot_pool"])
        
        response = {
            "type": "subscription_response",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "subscribed_channels": channels,
            "access_level": access_level
        }
        
        await websocket.send(json.dumps(response))
    
    async def _process_data_queue(self):
        """Обработчик очереди данных от сканнера"""
        while self.is_running:
            try:
                # Ждем данные из очереди с таймаутом
                try:
                    data_item = await asyncio.wait_for(
                        self.data_queue.get(), timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                
                # Обрабатываем данные в зависимости от типа
                data_type = data_item.get("type")
                
                if data_type == "hot_pool_update":
                    await self.broadcaster.broadcast_hot_pool_update(
                        data_item.get("data", {})
                    )
                    
                elif data_type == "system_stats":
                    await self.broadcaster.broadcast_system_stats(
                        data_item.get("data", {})
                    )
                
                # Отмечаем задачу как выполненную
                self.data_queue.task_done()
                
            except Exception as e:
                self.logger.error("Error processing data queue", error=str(e))
    
    async def send_hot_pool_data(self, hot_pool_data: Dict):
        """
        Отправка данных горячего пула через WebSocket
        
        Args:
            hot_pool_data: Данные горячего пула
        """
        if not self.is_running:
            return
        
        data_item = {
            "type": "hot_pool_update",
            "data": hot_pool_data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await self.data_queue.put(data_item)
    
    async def send_system_stats(self, stats_data: Dict):
        """
        Отправка системной статистики
        
        Args:
            stats_data: Статистика системы
        """
        if not self.is_running:
            return
        
        data_item = {
            "type": "system_stats", 
            "data": stats_data,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        await self.data_queue.put(data_item)
    
    async def _get_server_stats(self) -> Dict:
        """Получить статистику сервера"""
        uptime = None
        if self.start_time:
            uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        
        return {
            "server": {
                "is_running": self.is_running,
                "host": self.host,
                "port": self.port,
                "uptime_seconds": uptime,
                "connection_attempts": self.connection_attempts,
                "failed_connections": self.failed_connections
            },
            "broadcaster": self.broadcaster.get_stats(),
            "authenticator": self.authenticator.get_stats(),
            "data_queue_size": self.data_queue.qsize()
        }
    
    def get_stats(self) -> Dict:
        """Синхронная версия статистики"""
        return {
            "is_running": self.is_running,
            "host": self.host,
            "port": self.port,
            "connection_attempts": self.connection_attempts,
            "failed_connections": self.failed_connections,
            "data_queue_size": self.data_queue.qsize() if self.data_queue else 0
        }


# Глобальный экземпляр сервера
_websocket_server: Optional[WebSocketServer] = None


async def get_websocket_server() -> WebSocketServer:
    """Получить глобальный экземпляр WebSocket сервера"""
    global _websocket_server
    
    if _websocket_server is None:
        _websocket_server = WebSocketServer()
    
    return _websocket_server


async def start_websocket_server():
    """Запуск глобального WebSocket сервера"""
    server = await get_websocket_server()
    await server.start()
    return server


async def stop_websocket_server():
    """Остановка глобального WebSocket сервера"""
    global _websocket_server
    
    if _websocket_server:
        await _websocket_server.stop()
        _websocket_server = None
CryptoScannerWebSocket = WebSocketServer
