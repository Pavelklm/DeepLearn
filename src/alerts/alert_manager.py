"""
Система алертов и уведомлений
"""

import asyncio
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path

from src.utils.logger import get_component_logger

logger = get_component_logger("alerts")


class AlertLevel(Enum):
    """Уровни важности алертов"""
    INFO = "info"
    WARNING = "warning" 
    CRITICAL = "critical"
    EMERGENCY = "emergency"


class AlertType(Enum):
    """Типы алертов"""
    SYSTEM_HEALTH = "system_health"
    PERFORMANCE = "performance"
    DIAMOND_ORDER = "diamond_order"
    HIGH_VALUE_ORDER = "high_value_order"
    MARKET_ANOMALY = "market_anomaly"
    API_ERROR = "api_error"
    CONNECTION_LOST = "connection_lost"


@dataclass
class Alert:
    """Структура алерта"""
    id: str
    timestamp: datetime
    level: AlertLevel
    type: AlertType
    title: str
    message: str
    
    # Контекстная информация
    component: Optional[str] = None
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    
    # Данные алерта
    data: Optional[Dict[str, Any]] = None
    
    # Метаданные
    acknowledged: bool = False
    resolved: bool = False
    resolved_at: Optional[datetime] = None
    
    def __post_init__(self):
        if self.data is None:
            self.data = {}


class AlertRule:
    """Правило для создания алертов"""
    
    def __init__(self, 
                 rule_id: str,
                 alert_type: AlertType,
                 alert_level: AlertLevel,
                 condition_func: Callable[[Dict], bool],
                 title_template: str,
                 message_template: str,
                 cooldown_seconds: int = 300):
        """
        Args:
            rule_id: Уникальный ID правила
            alert_type: Тип алерта
            alert_level: Уровень важности
            condition_func: Функция проверки условия
            title_template: Шаблон заголовка
            message_template: Шаблон сообщения
            cooldown_seconds: Время блокировки повторных алертов
        """
        self.rule_id = rule_id
        self.alert_type = alert_type
        self.alert_level = alert_level
        self.condition_func = condition_func
        self.title_template = title_template
        self.message_template = message_template
        self.cooldown_seconds = cooldown_seconds
        
        # Состояние правила
        self.last_triggered = None
        self.trigger_count = 0
        self.is_active = True
    
    def check_condition(self, context: Dict) -> bool:
        """Проверка условия срабатывания"""
        if not self.is_active:
            return False
        
        # Проверяем cooldown
        if self.last_triggered:
            cooldown_expires = self.last_triggered + timedelta(seconds=self.cooldown_seconds)
            if datetime.now(timezone.utc) < cooldown_expires:
                return False
        
        try:
            return self.condition_func(context)
        except Exception as e:
            logger.warning("Error in alert rule condition", 
                          rule_id=self.rule_id, error=str(e))
            return False
    
    def create_alert(self, context: Dict) -> Alert:
        """Создание алерта на основе контекста"""
        alert_id = f"{self.rule_id}_{int(datetime.now(timezone.utc).timestamp())}"
        
        # Форматируем заголовок и сообщение
        try:
            title = self.title_template.format(**context)
            message = self.message_template.format(**context)
        except KeyError as e:
            title = f"Alert: {self.rule_id}"
            message = f"Alert triggered but template formatting failed: {e}"
        
        # Обновляем состояние правила
        self.last_triggered = datetime.now(timezone.utc)
        self.trigger_count += 1
        
        return Alert(
            id=alert_id,
            timestamp=datetime.now(timezone.utc),
            level=self.alert_level,
            type=self.alert_type,
            title=title,
            message=message,
            component=context.get('component'),
            symbol=context.get('symbol'),
            exchange=context.get('exchange'),
            data=context.copy()
        )


class AlertManager:
    """Менеджер системы алертов"""
    
    def __init__(self):
        self.logger = logger
        
        # Хранилище алертов и правил
        self.active_alerts: Dict[str, Alert] = {}
        self.alert_history: List[Alert] = []
        self.alert_rules: Dict[str, AlertRule] = {}
        
        # Обработчики уведомлений
        self.notification_handlers: Dict[str, Callable] = {}
        
        # Конфигурация
        self.max_history_size = 1000
        self.auto_resolve_timeout = 3600  # 1 час
        
        # Файлы для сохранения
        self.alerts_file = Path("data/alerts.json")
        self.alerts_file.parent.mkdir(exist_ok=True)
        
        # Задачи
        self.cleanup_task = None
        self.save_task = None
        self.is_running = False
        
        # Загружаем стандартные правила
        self._setup_default_rules()
    
    def _setup_default_rules(self):
        """Настройка стандартных правил алертов"""
        
        # Алерт критического состояния компонента
        self.add_rule(AlertRule(
            rule_id="component_critical",
            alert_type=AlertType.SYSTEM_HEALTH,
            alert_level=AlertLevel.CRITICAL,
            condition_func=lambda ctx: ctx.get('health_status') == 'critical',
            title_template="Critical: {component} system failure",
            message_template="Component {component} is in critical state: {message}",
            cooldown_seconds=300
        ))
        
        # Алерт высокого error rate
        self.add_rule(AlertRule(
            rule_id="high_error_rate",
            alert_type=AlertType.PERFORMANCE,
            alert_level=AlertLevel.WARNING,
            condition_func=lambda ctx: ctx.get('error_rate', 0) > 0.1,
            title_template="High Error Rate: {component}",
            message_template="Component {component} has error rate {error_rate:.2%}, threshold exceeded",
            cooldown_seconds=600
        ))
        
        # Алерт diamond ордера
        self.add_rule(AlertRule(
            rule_id="diamond_order_detected",
            alert_type=AlertType.DIAMOND_ORDER,
            alert_level=AlertLevel.INFO,
            condition_func=lambda ctx: (
                ctx.get('category') == 'diamond' and 
                ctx.get('usd_value', 0) > 10000
            ),
            title_template="💎 Diamond Order: {symbol}",
            message_template="Diamond order detected: {symbol} ${usd_value:,.2f} (weight: {weight:.3f})",
            cooldown_seconds=60
        ))
        
        # Алерт очень больших ордеров
        self.add_rule(AlertRule(
            rule_id="high_value_order",
            alert_type=AlertType.HIGH_VALUE_ORDER,
            alert_level=AlertLevel.WARNING,
            condition_func=lambda ctx: ctx.get('usd_value', 0) > 100000,
            title_template="🚨 Large Order: {symbol}",
            message_template="Very large order: {symbol} ${usd_value:,.2f} - {side} at ${price}",
            cooldown_seconds=300
        ))
        
        # Алерт потери соединения
        self.add_rule(AlertRule(
            rule_id="connection_lost", 
            alert_type=AlertType.CONNECTION_LOST,
            alert_level=AlertLevel.CRITICAL,
            condition_func=lambda ctx: not ctx.get('is_connected', True),
            title_template="Connection Lost: {component}",
            message_template="Lost connection to {component} ({exchange})",
            cooldown_seconds=60
        ))
        
        # Алерт медленного API
        self.add_rule(AlertRule(
            rule_id="slow_api_response",
            alert_type=AlertType.PERFORMANCE,
            alert_level=AlertLevel.WARNING,
            condition_func=lambda ctx: ctx.get('avg_response_time', 0) > 5.0,
            title_template="Slow API Response: {component}",
            message_template="API response time is {avg_response_time:.2f}s (threshold: 5.0s)",
            cooldown_seconds=300
        ))
    
    def add_rule(self, rule: AlertRule):
        """Добавление правила алерта"""
        self.alert_rules[rule.rule_id] = rule
        self.logger.debug("Alert rule added", rule_id=rule.rule_id, type=rule.alert_type.value)
    
    def remove_rule(self, rule_id: str):
        """Удаление правила алерта"""
        if rule_id in self.alert_rules:
            del self.alert_rules[rule_id]
            self.logger.debug("Alert rule removed", rule_id=rule_id)
    
    def add_notification_handler(self, name: str, handler: Callable[[Alert], None]):
        """Добавление обработчика уведомлений"""
        self.notification_handlers[name] = handler
        self.logger.info("Notification handler added", name=name)
    
    def remove_notification_handler(self, name: str):
        """Удаление обработчика уведомлений"""
        if name in self.notification_handlers:
            del self.notification_handlers[name]
            self.logger.info("Notification handler removed", name=name)
    
    async def start(self):
        """Запуск системы алертов"""
        if self.is_running:
            return
        
        self.is_running = True
        
        # Запускаем задачи обслуживания
        self.cleanup_task = asyncio.create_task(self._cleanup_loop())
        self.save_task = asyncio.create_task(self._save_loop())
        
        self.logger.info("Alert system started", 
                        rules_count=len(self.alert_rules),
                        handlers_count=len(self.notification_handlers))
    
    async def stop(self):
        """Остановка системы алертов"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # Останавливаем задачи
        if self.cleanup_task:
            self.cleanup_task.cancel()
            try:
                await self.cleanup_task
            except asyncio.CancelledError:
                pass
        
        if self.save_task:
            self.save_task.cancel()
            try:
                await self.save_task
            except asyncio.CancelledError:
                pass
        
        # Финальное сохранение
        await self._save_alerts()
        
        self.logger.info("Alert system stopped")
    
    async def check_conditions(self, context: Dict):
        """Проверка всех условий алертов"""
        if not self.is_running:
            return
        
        triggered_alerts = []
        
        for rule in self.alert_rules.values():
            if rule.check_condition(context):
                alert = rule.create_alert(context)
                triggered_alerts.append(alert)
        
        # Обрабатываем сработавшие алерты
        for alert in triggered_alerts:
            await self._process_alert(alert)
    
    async def _process_alert(self, alert: Alert):
        """Обработка нового алерта"""
        try:
            # Добавляем в активные алерты
            self.active_alerts[alert.id] = alert
            
            # Добавляем в историю
            self.alert_history.append(alert)
            
            # Ограничиваем размер истории
            if len(self.alert_history) > self.max_history_size:
                self.alert_history = self.alert_history[-self.max_history_size:]
            
            self.logger.info("Alert triggered", 
                           alert_id=alert.id,
                           level=alert.level.value,
                           type=alert.type.value,
                           title=alert.title)
            
            # Отправляем уведомления
            await self._send_notifications(alert)
            
        except Exception as e:
            self.logger.error("Error processing alert", alert_id=alert.id, error=str(e))
    
    async def _send_notifications(self, alert: Alert):
        """Отправка уведомлений через все обработчики"""
        for handler_name, handler in self.notification_handlers.items():
            try:
                if asyncio.iscoroutinefunction(handler):
                    await handler(alert)
                else:
                    handler(alert)
                    
            except Exception as e:
                self.logger.error("Error in notification handler", 
                                handler=handler_name, 
                                alert_id=alert.id, 
                                error=str(e))
    
    async def acknowledge_alert(self, alert_id: str, user: str = "system"):
        """Подтверждение алерта"""
        if alert_id in self.active_alerts:
            alert = self.active_alerts[alert_id]
            alert.acknowledged = True
            
            self.logger.info("Alert acknowledged", 
                           alert_id=alert_id, user=user)
    
    async def resolve_alert(self, alert_id: str, user: str = "system"):
        """Решение алерта"""
        if alert_id in self.active_alerts:
            alert = self.active_alerts[alert_id]
            alert.resolved = True
            alert.resolved_at = datetime.now(timezone.utc)
            
            # Удаляем из активных
            del self.active_alerts[alert_id]
            
            self.logger.info("Alert resolved", 
                           alert_id=alert_id, user=user)
    
    async def _cleanup_loop(self):
        """Цикл очистки старых алертов"""
        while self.is_running:
            try:
                await asyncio.sleep(300)  # Каждые 5 минут
                await self._cleanup_old_alerts()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in cleanup loop", error=str(e))
    
    async def _cleanup_old_alerts(self):
        """Очистка старых алертов"""
        cutoff_time = datetime.now(timezone.utc) - timedelta(seconds=self.auto_resolve_timeout)
        
        to_resolve = []
        for alert_id, alert in self.active_alerts.items():
            if alert.timestamp < cutoff_time and not alert.acknowledged:
                to_resolve.append(alert_id)
        
        for alert_id in to_resolve:
            await self.resolve_alert(alert_id, "auto-cleanup")
    
    async def _save_loop(self):
        """Цикл сохранения алертов"""
        while self.is_running:
            try:
                await asyncio.sleep(300)  # Каждые 5 минут
                await self._save_alerts()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in save loop", error=str(e))
    
    async def _save_alerts(self):
        """Сохранение алертов в файл"""
        try:
            export_data = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'active_alerts': {
                    alert_id: {
                        **asdict(alert),
                        'timestamp': alert.timestamp.isoformat(),
                        'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None,
                        'level': alert.level.value,
                        'type': alert.type.value
                    }
                    for alert_id, alert in self.active_alerts.items()
                },
                'recent_history': [
                    {
                        **asdict(alert),
                        'timestamp': alert.timestamp.isoformat(),
                        'resolved_at': alert.resolved_at.isoformat() if alert.resolved_at else None,
                        'level': alert.level.value,
                        'type': alert.type.value
                    }
                    for alert in self.alert_history[-100:]  # Последние 100 алертов
                ]
            }
            
            # Атомарная запись
            temp_file = self.alerts_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            temp_file.replace(self.alerts_file)
            
        except Exception as e:
            self.logger.error("Error saving alerts", error=str(e))
    
    def get_active_alerts(self, level: AlertLevel = None) -> List[Alert]:
        """Получить активные алерты"""
        alerts = list(self.active_alerts.values())
        
        if level:
            alerts = [a for a in alerts if a.level == level]
        
        return sorted(alerts, key=lambda x: x.timestamp, reverse=True)
    
    def get_alert_stats(self) -> Dict:
        """Получить статистику алертов"""
        active_by_level = {}
        for alert in self.active_alerts.values():
            level = alert.level.value
            active_by_level[level] = active_by_level.get(level, 0) + 1
        
        # Статистика по последним 24 часам
        cutoff_24h = datetime.now(timezone.utc) - timedelta(hours=24)
        recent_alerts = [a for a in self.alert_history if a.timestamp >= cutoff_24h]
        
        recent_by_level = {}
        for alert in recent_alerts:
            level = alert.level.value
            recent_by_level[level] = recent_by_level.get(level, 0) + 1
        
        return {
            'active_alerts_total': len(self.active_alerts),
            'active_by_level': active_by_level,
            'total_history': len(self.alert_history),
            'recent_24h_total': len(recent_alerts),
            'recent_24h_by_level': recent_by_level,
            'rules_count': len(self.alert_rules),
            'handlers_count': len(self.notification_handlers),
            'is_running': self.is_running
        }


# Глобальный экземпляр менеджера алертов
_alert_manager: Optional[AlertManager] = None


def get_alert_manager() -> AlertManager:
    """Получить глобальный экземпляр менеджера алертов"""
    global _alert_manager
    
    if _alert_manager is None:
        _alert_manager = AlertManager()
    
    return _alert_manager


async def start_alerts():
    """Запуск глобальной системы алертов"""
    manager = get_alert_manager()
    await manager.start()
    return manager


async def stop_alerts():
    """Остановка глобальной системы алертов"""
    global _alert_manager
    
    if _alert_manager:
        await _alert_manager.stop()
        _alert_manager = None


# Удобные функции для создания алертов
async def alert_diamond_order(symbol: str, usd_value: float, weight: float, **kwargs):
    """Создать алерт diamond ордера"""
    manager = get_alert_manager()
    context = {
        'category': 'diamond',
        'symbol': symbol,
        'usd_value': usd_value,
        'weight': weight,
        **kwargs
    }
    await manager.check_conditions(context)


async def alert_system_health(component: str, health_status: str, message: str, **kwargs):
    """Создать алерт состояния системы"""
    manager = get_alert_manager()
    context = {
        'component': component,
        'health_status': health_status,
        'message': message,
        **kwargs
    }
    await manager.check_conditions(context)
