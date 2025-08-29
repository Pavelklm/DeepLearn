"""
Система алертов для мониторинга сканера больших ордеров
Согласно спецификации
"""

import asyncio
import json
import aiofiles
from datetime import datetime, timezone
from typing import Dict, List, Optional
from pathlib import Path
from enum import Enum

# Добавляем корневую директорию в путь
import sys
sys.path.append(str(Path(__file__).parent.parent))

from config.main_config import MONITORING_CONFIG

class AlertLevel(Enum):
    """Уровни критичности алертов"""
    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"

class AlertManager:
    """Менеджер алертов согласно спецификации"""
    
    def __init__(self):
        self.alerts_file = Path("data/alerts.json")
        self.active_alerts = {}
        self.alert_history = []
        
    async def check_critical_metrics(self, metrics: Dict) -> List[Dict]:
        """Проверка критических метрик из спецификации"""
        alerts = []
        
        # Проверяем все метрики из CRITICAL_METRICS спецификации
        critical_metrics = {
            # Производительность
            "api_response_time": {"threshold": 2.0, "unit": "seconds"},
            "websocket_latency": {"threshold": 0.1, "unit": "seconds"},
            "memory_usage": {"threshold": 80, "unit": "percent"},
            "cpu_usage": {"threshold": 90, "unit": "percent"},
            
            # Функциональность
            "active_orders_count": {"min": 1, "max": 10000},
            "hot_pool_size": {"min": 0, "max": 500},
            "websocket_connections": {"max": 1000},
            "failed_api_calls": {"threshold": 10, "period": "1min"},
            
            # Бизнес-метрики
            "diamond_orders_per_hour": {"min": 5},
            "average_order_lifetime": {"min": 60, "unit": "seconds"},
            "exchange_coverage": {"min": 1},  # Количество рабочих бирж
        }
        
        # API response time
        if metrics.get("avg_response_time_ms", 0) > 2000:
            alerts.append(self._create_alert(
                AlertLevel.CRITICAL,
                "api_response_time",
                f"API response time {metrics.get('avg_response_time_ms')}ms > 2000ms"
            ))
        
        # Memory usage
        memory_percent = metrics.get("memory_usage_percent", 0)
        if memory_percent > 80:
            level = AlertLevel.CRITICAL if memory_percent > 90 else AlertLevel.WARNING
            alerts.append(self._create_alert(
                level,
                "memory_usage",
                f"Memory usage {memory_percent}% exceeds threshold"
            ))
        
        # CPU usage
        cpu_percent = metrics.get("cpu_usage_percent", 0)
        if cpu_percent > 90:
            alerts.append(self._create_alert(
                AlertLevel.CRITICAL,
                "cpu_usage",
                f"CPU usage {cpu_percent}% > 90%"
            ))
        
        # Hot pool activity
        hot_pool_orders = metrics.get("hot_pool_orders", 0)
        if hot_pool_orders == 0:
            alerts.append(self._create_alert(
                AlertLevel.WARNING,
                "hot_pool_empty",
                "Hot pool has no orders for extended period"
            ))
        
        # Exchange connectivity
        exchanges_connected = len([
            ex for ex in metrics.get("exchanges", {}).values() 
            if ex.get("connected", False)
        ])
        if exchanges_connected < 1:
            alerts.append(self._create_alert(
                AlertLevel.CRITICAL,
                "exchange_connectivity",
                "No exchanges connected"
            ))
        
        # WebSocket connections
        total_ws_connections = metrics.get("websocket_connections", {}).get("total", 0)
        if total_ws_connections > 1000:
            alerts.append(self._create_alert(
                AlertLevel.WARNING,
                "websocket_overload",
                f"WebSocket connections {total_ws_connections} > 1000"
            ))
        
        # Failed API calls rate
        failed_requests = metrics.get("failed_api_requests", 0)
        total_requests = metrics.get("total_api_requests", 1)
        error_rate = failed_requests / total_requests if total_requests > 0 else 0
        
        if error_rate > 0.1:  # 10% error rate
            alerts.append(self._create_alert(
                AlertLevel.CRITICAL,
                "high_error_rate",
                f"API error rate {error_rate:.1%} > 10%"
            ))
        
        return alerts
    
    def _create_alert(self, level: AlertLevel, metric: str, message: str) -> Dict:
        """Создание алерта"""
        alert = {
            "id": f"{metric}_{datetime.now().timestamp()}",
            "level": level.value,
            "metric": metric,
            "message": message,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "resolved": False,
            "acknowledged": False
        }
        
        return alert
    
    async def process_alerts(self, new_alerts: List[Dict]):
        """Обработка новых алертов"""
        for alert in new_alerts:
            alert_key = f"{alert['metric']}_{alert['level']}"
            
            # Проверяем, не дублируется ли алерт
            if alert_key not in self.active_alerts:
                self.active_alerts[alert_key] = alert
                self.alert_history.append(alert)
                
                # Отправляем алерт
                await self._send_alert(alert)
        
        # Сохраняем алерты
        await self._save_alerts()
    
    async def _send_alert(self, alert: Dict):
        """Отправка алерта (заглушка для реальных каналов)"""
        # В спецификации упоминались Telegram/Discord
        alert_channels = {
            "critical": "telegram_bot_token",
            "warning": "discord_webhook_url", 
            "info": "log_only"
        }
        
        level = alert["level"]
        message = f"🚨 [{level.upper()}] {alert['message']}"
        
        # Пока просто выводим в консоль
        print(f"ALERT: {message}")
        
        # TODO: Реальная отправка через Telegram/Discord API
        # if level == "critical":
        #     await send_telegram_alert(message)
        # elif level == "warning":
        #     await send_discord_alert(message)
    
    async def resolve_alert(self, alert_id: str):
        """Закрытие алерта"""
        for key, alert in self.active_alerts.items():
            if alert["id"] == alert_id:
                alert["resolved"] = True
                alert["resolved_at"] = datetime.now(timezone.utc).isoformat()
                del self.active_alerts[key]
                break
        
        await self._save_alerts()
    
    async def _save_alerts(self):
        """Сохранение алертов в файл"""
        try:
            data = {
                "active_alerts": list(self.active_alerts.values()),
                "alert_history": self.alert_history[-100:],  # Последние 100
                "last_updated": datetime.now(timezone.utc).isoformat()
            }
            
            async with aiofiles.open(self.alerts_file, 'w') as f:
                await f.write(json.dumps(data, indent=2))
                
        except Exception as e:
            print(f"Ошибка сохранения алертов: {e}")
    
    async def load_alerts(self):
        """Загрузка алертов из файла"""
        try:
            if self.alerts_file.exists():
                async with aiofiles.open(self.alerts_file, 'r') as f:
                    data = json.loads(await f.read())
                    
                self.active_alerts = {
                    f"{alert['metric']}_{alert['level']}": alert 
                    for alert in data.get("active_alerts", [])
                }
                self.alert_history = data.get("alert_history", [])
                
        except Exception as e:
            print(f"Ошибка загрузки алертов: {e}")
    
    def get_alert_stats(self) -> Dict:
        """Получение статистики алертов"""
        return {
            "active_alerts": len(self.active_alerts),
            "total_alerts_today": len([
                alert for alert in self.alert_history
                if alert["timestamp"].startswith(datetime.now().strftime("%Y-%m-%d"))
            ]),
            "critical_alerts": len([
                alert for alert in self.active_alerts.values()
                if alert["level"] == "critical"
            ]),
            "warning_alerts": len([
                alert for alert in self.active_alerts.values()
                if alert["level"] == "warning"
            ]),
            "info_alerts": len([
                alert for alert in self.active_alerts.values()
                if alert["level"] == "info"
            ])
        }


# Глобальный менеджер алертов
alert_manager = AlertManager()


async def check_and_send_alerts(metrics: Dict):
    """Основная функция проверки и отправки алертов"""
    await alert_manager.load_alerts()
    
    # Проверяем метрики
    new_alerts = await alert_manager.check_critical_metrics(metrics)
    
    # Обрабатываем новые алерты
    if new_alerts:
        await alert_manager.process_alerts(new_alerts)
    
    return alert_manager.get_alert_stats()


if __name__ == "__main__":
    # Тестовая проверка алертов
    test_metrics = {
        "cpu_usage_percent": 95.0,
        "memory_usage_percent": 85.0,
        "avg_response_time_ms": 3000,
        "hot_pool_orders": 0,
        "exchanges": {
            "binance": {"connected": False}
        }
    }
    
    asyncio.run(check_and_send_alerts(test_metrics))
