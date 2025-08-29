"""
Обработчики уведомлений для системы алертов
"""

import asyncio
from datetime import datetime
from typing import Dict, Any

from src.alerts.alert_manager import Alert, AlertLevel
from src.utils.logger import get_component_logger

logger = get_component_logger("alert_handlers")


class LogNotificationHandler:
    """Обработчик уведомлений через логирование"""
    
    def __init__(self):
        self.logger = logger
        self.notification_count = 0
        
    async def handle_alert(self, alert: Alert):
        """Обработка алерта через логирование"""
        self.notification_count += 1
        
        # Определяем уровень логирования
        if alert.level == AlertLevel.CRITICAL or alert.level == AlertLevel.EMERGENCY:
            log_level = "error"
        elif alert.level == AlertLevel.WARNING:
            log_level = "warning" 
        else:
            log_level = "info"
        
        # Формируем сообщение
        log_data = {
            "alert_id": alert.id,
            "alert_level": alert.level.value,
            "alert_type": alert.type.value,
            "title": alert.title,
            "message": alert.message,
            "component": alert.component,
            "symbol": alert.symbol,
            "exchange": alert.exchange
        }
        
        # Добавляем важные данные
        if alert.data:
            if "usd_value" in alert.data:
                log_data["usd_value"] = alert.data["usd_value"]
            if "weight" in alert.data:
                log_data["weight"] = alert.data["weight"]
        
        # Логируем в зависимости от уровня
        if log_level == "error":
            self.logger.error("🚨 CRITICAL ALERT", **log_data)
        elif log_level == "warning":
            self.logger.warning("⚠️  ALERT", **log_data) 
        else:
            self.logger.info("💎 ALERT", **log_data)


class ConsoleNotificationHandler:
    """Обработчик уведомлений в консоль"""
    
    def __init__(self):
        self.notification_count = 0
        
    async def handle_alert(self, alert: Alert):
        """Вывод алерта в консоль"""
        self.notification_count += 1
        
        # Эмодзи для разных типов алертов
        emoji_map = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️", 
            AlertLevel.CRITICAL: "🚨",
            AlertLevel.EMERGENCY: "🔥"
        }
        
        emoji = emoji_map.get(alert.level, "📢")
        
        # Форматируем время
        time_str = alert.timestamp.strftime("%H:%M:%S")
        
        print(f"\n{emoji} [{time_str}] {alert.title}")
        print(f"   {alert.message}")
        
        # Дополнительная информация для важных алертов
        if alert.level in [AlertLevel.WARNING, AlertLevel.CRITICAL, AlertLevel.EMERGENCY]:
            if alert.component:
                print(f"   Component: {alert.component}")
            if alert.symbol:
                print(f"   Symbol: {alert.symbol}")
            if alert.data and "usd_value" in alert.data:
                print(f"   Value: ${alert.data['usd_value']:,.2f}")


class FileNotificationHandler:
    """Обработчик уведомлений в файл"""
    
    def __init__(self, filename: str = "data/alerts_notifications.log"):
        self.filename = filename
        self.notification_count = 0
        
    async def handle_alert(self, alert: Alert):
        """Сохранение алерта в файл"""
        self.notification_count += 1
        
        try:
            # Форматируем строку для записи
            timestamp = alert.timestamp.isoformat()
            line = f"[{timestamp}] {alert.level.value.upper()} | {alert.type.value} | {alert.title} | {alert.message}"
            
            if alert.symbol:
                line += f" | Symbol: {alert.symbol}"
            if alert.data and "usd_value" in alert.data:
                line += f" | Value: ${alert.data['usd_value']:,.2f}"
            
            line += "\n"
            
            # Записываем в файл
            import aiofiles
            async with aiofiles.open(self.filename, mode='a', encoding='utf-8') as f:
                await f.write(line)
                
        except Exception as e:
            logger.error("Error writing alert to file", filename=self.filename, error=str(e))


async def setup_default_handlers(alert_manager):
    """Настройка стандартных обработчиков уведомлений"""
    
    # Обработчик логирования (всегда активен)
    log_handler = LogNotificationHandler()
    alert_manager.add_notification_handler("log", log_handler.handle_alert)
    
    # Обработчик консоли (для важных алертов)
    console_handler = ConsoleNotificationHandler()
    
    async def console_filter(alert: Alert):
        """Фильтр для консольного вывода - только важные алерты"""
        if alert.level in [AlertLevel.WARNING, AlertLevel.CRITICAL, AlertLevel.EMERGENCY]:
            await console_handler.handle_alert(alert)
    
    alert_manager.add_notification_handler("console", console_filter)
    
    # Обработчик файла (для diamond ордеров и критических алертов)
    file_handler = FileNotificationHandler()
    
    async def file_filter(alert: Alert):
        """Фильтр для файлового вывода"""
        if (alert.type.value == "diamond_order" or 
            alert.level in [AlertLevel.CRITICAL, AlertLevel.EMERGENCY]):
            await file_handler.handle_alert(alert)
    
    alert_manager.add_notification_handler("file", file_filter)
    
    logger.info("Default alert handlers configured",
                handlers=["log", "console", "file"])


# Дополнительные функции для интеграции с внешними системами

async def webhook_handler(alert: Alert, webhook_url: str):
    """Отправка алерта через webhook"""
    try:
        import aiohttp
        import json
        
        payload = {
            "timestamp": alert.timestamp.isoformat(),
            "level": alert.level.value,
            "type": alert.type.value, 
            "title": alert.title,
            "message": alert.message,
            "component": alert.component,
            "symbol": alert.symbol,
            "exchange": alert.exchange,
            "data": alert.data
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, 
                                   json=payload,
                                   timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    logger.debug("Webhook alert sent successfully", url=webhook_url)
                else:
                    logger.warning("Webhook alert failed", 
                                 url=webhook_url, status=response.status)
                                 
    except Exception as e:
        logger.error("Error sending webhook alert", url=webhook_url, error=str(e))


async def email_handler(alert: Alert, smtp_config: Dict[str, Any]):
    """Отправка алерта по email"""
    try:
        import aiosmtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart
        
        # Создаем email сообщение
        msg = MIMEMultipart()
        msg['From'] = smtp_config['from_email']
        msg['To'] = smtp_config['to_email']
        msg['Subject'] = f"Scanner Alert: {alert.title}"
        
        # Текст сообщения
        body = f"""
Alert Details:
- Level: {alert.level.value.upper()}
- Type: {alert.type.value}
- Time: {alert.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}
- Component: {alert.component or 'N/A'}
- Symbol: {alert.symbol or 'N/A'}
- Exchange: {alert.exchange or 'N/A'}

Message: {alert.message}
        """
        
        if alert.data:
            body += f"\nAdditional Data: {alert.data}"
        
        msg.attach(MIMEText(body, 'plain'))
        
        # Отправляем
        await aiosmtplib.send(
            msg,
            hostname=smtp_config['hostname'],
            port=smtp_config['port'],
            use_tls=smtp_config.get('use_tls', True),
            username=smtp_config.get('username'),
            password=smtp_config.get('password')
        )
        
        logger.debug("Email alert sent successfully", to=smtp_config['to_email'])
        
    except Exception as e:
        logger.error("Error sending email alert", error=str(e))
