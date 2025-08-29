"""
REST API для получения статистики и управления сканнером
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from pathlib import Path

import aiohttp
from aiohttp import web, web_response
from aiohttp.web import Request, Response

from src.utils.logger import get_component_logger

logger = get_component_logger("api_server")


class ScannerAPIServer:
    """REST API сервер для управления сканнером"""
    
    def __init__(self, host: str = "localhost", port: int = 8080):
        self.host = host
        self.port = port
        self.logger = logger
        
        # Ссылки на компоненты системы
        self.orchestrator = None
        self.system_monitor = None
        self.alert_manager = None
        
        # Веб сервер
        self.app = None
        self.runner = None
        self.site = None
        
        self.is_running = False
        
        # Статистика API
        self.request_count = 0
        self.error_count = 0
        self.start_time = None
    
    def setup_routes(self):
        """Настройка маршрутов API"""
        self.app = web.Application()
        
        # Основные статистики
        self.app.router.add_get('/api/stats', self.get_system_stats)
        self.app.router.add_get('/api/stats/components', self.get_component_stats)
        self.app.router.add_get('/api/stats/alerts', self.get_alert_stats)
        
        # Данные пулов
        self.app.router.add_get('/api/pools/hot', self.get_hot_pool_data)
        self.app.router.add_get('/api/pools/observer', self.get_observer_pool_data)
        self.app.router.add_get('/api/pools/general', self.get_general_pool_data)
        
        # Управление алертами
        self.app.router.add_get('/api/alerts', self.get_alerts)
        self.app.router.add_post('/api/alerts/{alert_id}/acknowledge', self.acknowledge_alert)
        self.app.router.add_post('/api/alerts/{alert_id}/resolve', self.resolve_alert)
        
        # Управление системой
        self.app.router.add_get('/api/health', self.health_check)
        self.app.router.add_get('/api/version', self.get_version)
        
        # Статические файлы и документация
        self.app.router.add_get('/', self.serve_index)
        self.app.router.add_get('/docs', self.serve_docs)
        
        # Middleware для CORS и логирования
        self.app.middlewares.append(self.cors_middleware)
        self.app.middlewares.append(self.logging_middleware)
    
    async def start(self, orchestrator=None):
        """Запуск API сервера"""
        if self.is_running:
            return
        
        self.orchestrator = orchestrator
        
        # Получаем ссылки на компоненты
        if orchestrator:
            self.system_monitor = getattr(orchestrator, 'system_monitor', None)
            self.alert_manager = getattr(orchestrator, 'alert_manager', None)
        
        self.setup_routes()
        
        try:
            # Создаем и запускаем сервер
            self.runner = web.AppRunner(self.app)
            await self.runner.setup()
            
            self.site = web.TCPSite(self.runner, self.host, self.port)
            await self.site.start()
            
            self.is_running = True
            self.start_time = datetime.now(timezone.utc)
            
            self.logger.info("API server started", 
                           host=self.host, port=self.port,
                           url=f"http://{self.host}:{self.port}")
                           
        except Exception as e:
            self.logger.error("Failed to start API server", error=str(e))
            raise
    
    async def stop(self):
        """Остановка API сервера"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        try:
            if self.site:
                await self.site.stop()
            if self.runner:
                await self.runner.cleanup()
                
            self.logger.info("API server stopped")
            
        except Exception as e:
            self.logger.error("Error stopping API server", error=str(e))
    
    @web.middleware
    async def cors_middleware(self, request: Request, handler):
        """CORS middleware"""
        try:
            response = await handler(request)
            
            # Добавляем CORS заголовки
            response.headers['Access-Control-Allow-Origin'] = '*'
            response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
            response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
            
            return response
            
        except Exception as e:
            self.error_count += 1
            return web.json_response({'error': str(e)}, status=500)
    
    @web.middleware
    async def logging_middleware(self, request: Request, handler):
        """Middleware для логирования запросов"""
        start_time = datetime.now()
        self.request_count += 1
        
        try:
            response = await handler(request)
            
            duration = (datetime.now() - start_time).total_seconds()
            
            self.logger.debug("API request", 
                            method=request.method,
                            path=request.path,
                            status=response.status,
                            duration=f"{duration:.3f}s")
            
            return response
            
        except Exception as e:
            self.error_count += 1
            duration = (datetime.now() - start_time).total_seconds()
            
            self.logger.error("API request error",
                            method=request.method, 
                            path=request.path,
                            error=str(e),
                            duration=f"{duration:.3f}s")
            raise
    
    # API Handlers
    
    async def health_check(self, request: Request) -> Response:
        """Проверка здоровья API сервера"""
        uptime = None
        if self.start_time:
            uptime = (datetime.now(timezone.utc) - self.start_time).total_seconds()
        
        health_data = {
            'status': 'healthy' if self.is_running else 'unhealthy',
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'uptime_seconds': uptime,
            'requests_total': self.request_count,
            'errors_total': self.error_count,
            'orchestrator_connected': self.orchestrator is not None
        }
        
        return web.json_response(health_data)
    
    async def get_version(self, request: Request) -> Response:
        """Информация о версии"""
        version_data = {
            'name': 'Crypto Large Orders Scanner',
            'version': '1.0.0',
            'build_date': '2025-08-28',
            'api_version': 'v1',
            'python_version': '3.13+',
            'features': [
                'hot_pool_tracking',
                'websocket_streaming', 
                'real_time_monitoring',
                'adaptive_categorization',
                'multi_exchange_support'
            ]
        }
        
        return web.json_response(version_data)
    
    async def get_system_stats(self, request: Request) -> Response:
        """Общая статистика системы"""
        try:
            stats = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'api_server': {
                    'is_running': self.is_running,
                    'uptime_seconds': (datetime.now(timezone.utc) - self.start_time).total_seconds() if self.start_time else 0,
                    'requests_total': self.request_count,
                    'errors_total': self.error_count
                }
            }
            
            # Статистика orchestrator
            if self.orchestrator:
                orchestrator_stats = await self.orchestrator.get_system_stats()
                stats['orchestrator'] = orchestrator_stats
            
            # Статистика мониторинга
            if self.system_monitor:
                monitoring_stats = self.system_monitor.get_all_stats()
                stats['monitoring'] = monitoring_stats
            
            # Статистика алертов
            if self.alert_manager:
                alert_stats = self.alert_manager.get_alert_stats()
                stats['alerts'] = alert_stats
            
            return web.json_response(stats)
            
        except Exception as e:
            self.logger.error("Error getting system stats", error=str(e))
            return web.json_response({'error': str(e)}, status=500)
    
    async def get_hot_pool_data(self, request: Request) -> Response:
        """Данные горячего пула"""
        try:
            if not self.orchestrator or not self.orchestrator.hot_pool:
                return web.json_response({'error': 'Hot pool not available'}, status=404)
            
            hot_pool = self.orchestrator.hot_pool
            stats = hot_pool.get_stats()
            
            # Получаем данные ордеров
            orders_data = []
            for order_hash, hot_order in hot_pool.hot_orders.items():
                order_data = {
                    'order_hash': hot_order.order_hash,
                    'symbol': hot_order.symbol,
                    'exchange': hot_order.exchange,
                    'usd_value': hot_order.usd_value,
                    'side': hot_order.side,
                    'lifetime_seconds': hot_order.lifetime_seconds,
                    'growth_trend': hot_order.growth_trend,
                    'stability_score': hot_order.stability_score,
                    'weights': hot_order.weights,
                    'categories': hot_order.categories,
                    'first_seen': hot_order.first_seen.isoformat(),
                    'last_seen': hot_order.last_seen.isoformat()
                }
                orders_data.append(order_data)
            
            # Сортируем по весу
            orders_data.sort(key=lambda x: x.get('weights', {}).get('recommended', 0), reverse=True)
            
            result = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'stats': stats,
                'orders': orders_data[:50]  # Ограничиваем топ-50
            }
            
            return web.json_response(result)
            
        except Exception as e:
            self.logger.error("Error getting hot pool data", error=str(e))
            return web.json_response({'error': str(e)}, status=500)
    
    async def get_observer_pool_data(self, request: Request) -> Response:
        """Данные пула наблюдателя"""
        try:
            if not self.orchestrator or not self.orchestrator.observer_pool:
                return web.json_response({'error': 'Observer pool not available'}, status=404)
            
            observer_pool = self.orchestrator.observer_pool
            stats = observer_pool.get_stats()
            
            result = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'stats': stats
            }
            
            return web.json_response(result)
            
        except Exception as e:
            self.logger.error("Error getting observer pool data", error=str(e))
            return web.json_response({'error': str(e)}, status=500)
    
    async def get_general_pool_data(self, request: Request) -> Response:
        """Данные общего пула"""
        try:
            if not self.orchestrator or not self.orchestrator.general_pool:
                return web.json_response({'error': 'General pool not available'}, status=404)
            
            general_pool = self.orchestrator.general_pool
            stats = general_pool.get_stats()
            
            result = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'stats': stats
            }
            
            return web.json_response(result)
            
        except Exception as e:
            self.logger.error("Error getting general pool data", error=str(e))
            return web.json_response({'error': str(e)}, status=500)
    
    async def get_alerts(self, request: Request) -> Response:
        """Получить список алертов"""
        try:
            if not self.alert_manager:
                return web.json_response({'error': 'Alert manager not available'}, status=404)
            
            # Параметры запроса
            level_filter = request.query.get('level')
            limit = int(request.query.get('limit', 50))
            
            # Получаем активные алерты
            active_alerts = self.alert_manager.get_active_alerts()
            
            if level_filter:
                from src.alerts.alert_manager import AlertLevel
                try:
                    level_enum = AlertLevel(level_filter)
                    active_alerts = [a for a in active_alerts if a.level == level_enum]
                except ValueError:
                    pass  # Игнорируем неверный уровень
            
            # Ограничиваем количество
            active_alerts = active_alerts[:limit]
            
            # Форматируем для JSON
            alerts_data = []
            for alert in active_alerts:
                alert_data = {
                    'id': alert.id,
                    'timestamp': alert.timestamp.isoformat(),
                    'level': alert.level.value,
                    'type': alert.type.value,
                    'title': alert.title,
                    'message': alert.message,
                    'component': alert.component,
                    'symbol': alert.symbol,
                    'exchange': alert.exchange,
                    'acknowledged': alert.acknowledged,
                    'resolved': alert.resolved,
                    'data': alert.data
                }
                alerts_data.append(alert_data)
            
            result = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'total_active': len(self.alert_manager.active_alerts),
                'returned': len(alerts_data),
                'alerts': alerts_data,
                'stats': self.alert_manager.get_alert_stats()
            }
            
            return web.json_response(result)
            
        except Exception as e:
            self.logger.error("Error getting alerts", error=str(e))
            return web.json_response({'error': str(e)}, status=500)
    
    async def serve_index(self, request: Request) -> Response:
        """Главная страница"""
        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <title>Crypto Scanner API</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 40px; }}
                .status {{ padding: 10px; border-radius: 5px; }}
                .healthy {{ background-color: #d4edda; color: #155724; }}
                .info {{ background-color: #d1ecf1; color: #0c5460; }}
            </style>
        </head>
        <body>
            <h1>🔍 Crypto Large Orders Scanner</h1>
            
            <div class="status healthy">
                <h3>✅ API Server Status: Running</h3>
                <p>Server: {self.host}:{self.port}</p>
                <p>Uptime: {(datetime.now(timezone.utc) - self.start_time).total_seconds():.0f} seconds</p>
                <p>Requests: {self.request_count}</p>
            </div>
            
            <h2>📊 Available Endpoints</h2>
            <ul>
                <li><a href="/api/health">GET /api/health</a> - Server health check</li>
                <li><a href="/api/version">GET /api/version</a> - Version information</li>
                <li><a href="/api/stats">GET /api/stats</a> - System statistics</li>
                <li><a href="/api/pools/hot">GET /api/pools/hot</a> - Hot pool data</li>
                <li><a href="/api/pools/observer">GET /api/pools/observer</a> - Observer pool data</li>
                <li><a href="/api/alerts">GET /api/alerts</a> - Active alerts</li>
            </ul>
            
            <h2>🔌 WebSocket</h2>
            <div class="info">
                <p>WebSocket server available on port 8765</p>
                <ul>
                    <li>ws://localhost:8765/public - Public access</li>
                    <li>ws://localhost:8765/vip?key=YOUR_KEY - VIP access</li>
                    <li>ws://localhost:8765/private?token=YOUR_TOKEN - Private access</li>
                </ul>
            </div>
            
            <p><em>Generated at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}</em></p>
        </body>
        </html>
        """
        
        return web.Response(text=html, content_type='text/html')
    
    async def serve_docs(self, request: Request) -> Response:
        """Документация API"""
        docs = {
            'title': 'Crypto Scanner API Documentation',
            'version': '1.0.0',
            'base_url': f'http://{self.host}:{self.port}',
            'endpoints': {
                '/api/health': {
                    'method': 'GET',
                    'description': 'Check API server health',
                    'response': 'Server status and uptime information'
                },
                '/api/version': {
                    'method': 'GET', 
                    'description': 'Get version information',
                    'response': 'Version details and features'
                },
                '/api/stats': {
                    'method': 'GET',
                    'description': 'Get comprehensive system statistics',
                    'response': 'All system components statistics'
                },
                '/api/pools/hot': {
                    'method': 'GET',
                    'description': 'Get hot pool orders and statistics',
                    'response': 'Current hot pool orders with weights and categories'
                },
                '/api/pools/observer': {
                    'method': 'GET',
                    'description': 'Get observer pool statistics',
                    'response': 'Observer pool status and metrics'
                },
                '/api/alerts': {
                    'method': 'GET',
                    'description': 'Get active alerts',
                    'parameters': {
                        'level': 'Filter by alert level (info, warning, critical, emergency)',
                        'limit': 'Maximum number of alerts to return (default: 50)'
                    },
                    'response': 'List of active alerts with details'
                }
            },
            'websocket': {
                'url': f'ws://{self.host}:8765',
                'endpoints': {
                    '/public': 'Public access (diamond orders only, delayed)',
                    '/vip?key=KEY': 'VIP access (all orders, no delay)',
                    '/private?token=TOKEN': 'Private access (full data, no delay)'
                }
            }
        }
        
        return web.json_response(docs)
    
    # Пустые методы для совместимости (их можно расширить позднее)
    async def get_component_stats(self, request: Request) -> Response:
        """Статистика компонентов"""
        return web.json_response({'message': 'Component stats endpoint - coming soon'})
    
    async def get_alert_stats(self, request: Request) -> Response:
        """Статистика алертов"""
        if self.alert_manager:
            stats = self.alert_manager.get_alert_stats()
            return web.json_response(stats)
        return web.json_response({'error': 'Alert manager not available'}, status=404)
    
    async def acknowledge_alert(self, request: Request) -> Response:
        """Подтверждение алерта"""
        alert_id = request.match_info['alert_id']
        if self.alert_manager:
            await self.alert_manager.acknowledge_alert(alert_id, "api_user")
            return web.json_response({'message': f'Alert {alert_id} acknowledged'})
        return web.json_response({'error': 'Alert manager not available'}, status=404)
    
    async def resolve_alert(self, request: Request) -> Response:
        """Решение алерта"""
        alert_id = request.match_info['alert_id']
        if self.alert_manager:
            await self.alert_manager.resolve_alert(alert_id, "api_user")
            return web.json_response({'message': f'Alert {alert_id} resolved'})
        return web.json_response({'error': 'Alert manager not available'}, status=404)


# Глобальный экземпляр API сервера
_api_server: Optional[ScannerAPIServer] = None


def get_api_server(host: str = "localhost", port: int = 8080) -> ScannerAPIServer:
    """Получить глобальный экземпляр API сервера"""
    global _api_server
    
    if _api_server is None:
        _api_server = ScannerAPIServer(host, port)
    
    return _api_server


async def start_api_server(orchestrator=None, host: str = "localhost", port: int = 8080):
    """Запуск глобального API сервера"""
    server = get_api_server(host, port)
    await server.start(orchestrator)
    return server


async def stop_api_server():
    """Остановка глобального API сервера"""
    global _api_server
    
    if _api_server:
        await _api_server.stop()
        _api_server = None
