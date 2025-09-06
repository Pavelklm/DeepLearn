"""Модуль уведомлений через Telegram"""
import logging
import asyncio
from typing import Dict, Any
from telegram import Bot
from telegram.error import TelegramError
from .config_manager import Config


logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Класс для отправки уведомлений через Telegram"""
    
    def __init__(self, config: Config):
        """
        Инициализация Telegram уведомителя
        
        Args:
            config: Конфигурация системы с токенами Telegram
        """
        self.config = config  # Сохраняем конфигурацию
        self.bot = Bot(token=config.telegram_token)  # Создаем экземпляр бота
        self.chat_id = config.telegram_chat_id  # ID чата для отправки сообщений
        logger.info("Telegram уведомитель инициализирован")
    
    async def _send_message_async(self, message: str) -> bool:
        """
        Асинхронная отправка сообщения в Telegram
        
        Args:
            message: Текст сообщения для отправки
            
        Returns:
            bool: True если сообщение отправлено успешно
        """
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='HTML'  # Позволяет использовать HTML разметку
            )
            logger.info("Сообщение в Telegram отправлено успешно")
            return True
            
        except TelegramError as e:
            logger.error(f"Ошибка отправки сообщения в Telegram: {e}")
            return False
        except Exception as e:
            logger.error(f"Неожиданная ошибка при отправке в Telegram: {e}")
            return False
    
    def send_notification(self, message: str) -> bool:
        """
        Синхронная отправка уведомления в Telegram
        
        Args:
            message: Текст уведомления
            
        Returns:
            bool: True если уведомление отправлено успешно
        """
        logger.info(f"Отправляем уведомление: {message[:50]}...")
        
        try:
            # Запускаем асинхронную отправку в синхронном контексте
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self._send_message_async(message))
            loop.close()
            return result
            
        except Exception as e:
            logger.error(f"Ошибка при синхронной отправке уведомления: {e}")
            return False
    
    def notify_risk_limit_breach(self, limit_type: str, current_value: float, limit_value: float = None) -> bool:
        """
        Уведомление о нарушении лимитов риска
        
        Args:
            limit_type: Тип нарушенного лимита
            current_value: Текущее значение
            limit_value: Граничное значение лимита
            
        Returns:
            bool: True если уведомление отправлено
        """
        logger.warning(f"Нарушен лимит риска: {limit_type} = {current_value}")
        
        # Формируем сообщение в зависимости от типа лимита
        if limit_type == 'daily_drawdown':
            emoji = "📉"
            title = "ПРЕВЫШЕНА ДНЕВНАЯ ПРОСАДКА"
            description = f"Текущая просадка: <b>{current_value:.2%}</b>"
            if limit_value:
                description += f"\nЛимит: <b>{limit_value:.2%}</b>"
            action = "Торговля приостановлена на сегодня"
            
        elif limit_type == 'losing_days':
            emoji = "📊"
            title = "ПРЕВЫШЕНО КОЛИЧЕСТВО УБЫТОЧНЫХ ДНЕЙ"
            description = f"Убыточных дней подряд: <b>{int(current_value)}</b>"
            if limit_value:
                description += f"\nЛимит: <b>{int(limit_value)}</b>"
            action = "Торговля полностью остановлена"
            
        elif limit_type == 'consecutive_losses':
            emoji = "⚠️"
            title = "БОЛЬШАЯ СЕРИЯ УБЫТКОВ"
            description = f"Убытков подряд: <b>{int(current_value)}</b>"
            action = "Размер позиции снижен"
            
        else:
            emoji = "🚨"
            title = f"НАРУШЕН ЛИМИТ: {limit_type.upper()}"
            description = f"Текущее значение: <b>{current_value}</b>"
            action = "Проверьте настройки риск-менеджмента"
        
        # Составляем полное сообщение
        message = f"""
{emoji} <b>{title}</b>

{description}

🔧 <b>Действие:</b> {action}

⏰ <b>Время:</b> {self._get_current_time()}
"""
        
        return self.send_notification(message.strip())
    
    def notify_trade_executed(self, trade_details: Dict[str, Any]) -> bool:
        """
        Уведомление о выполненной сделке
        
        Args:
            trade_details: Детали выполненной сделки
            
        Returns:
            bool: True если уведомление отправлено
        """
        logger.info(f"Отправляем уведомление о сделке: {trade_details}")
        
        # Извлекаем данные сделки
        entry_price = trade_details.get('entry_price', 0)
        tp_price = trade_details.get('tp_price', 0)
        sl_price = trade_details.get('sl_price', 0)
        position_size = trade_details.get('position_size_usd', 0)
        order_id = trade_details.get('order_id', 'N/A')
        # symbol не используется - это модуль риск-менеджмента
        
        # Определяем направление сделки
        if tp_price > entry_price:
            direction = "LONG 📈"
            direction_emoji = "🟢"
        else:
            direction = "SHORT 📉"
            direction_emoji = "🔴"
        
        # Рассчитываем потенциальную прибыль/убыток
        potential_profit = abs(tp_price - entry_price) * (position_size / entry_price)
        potential_loss = abs(entry_price - sl_price) * (position_size / entry_price)
        risk_reward = potential_profit / potential_loss if potential_loss > 0 else 0
        
        message = f"""
{direction_emoji} <b>СДЕЛКА ОТКРЫТА</b>

📊 <b>Направление:</b> {direction}
🎯 <b>Вход:</b> ${entry_price:,.2f}
📈 <b>Take Profit:</b> ${tp_price:,.2f}
📉 <b>Stop Loss:</b> ${sl_price:,.2f}

💵 <b>Размер позиции:</b> ${position_size:,.2f}
💎 <b>Потенциал прибыли:</b> ${potential_profit:,.2f}
🔻 <b>Потенциал убытка:</b> ${potential_loss:,.2f}
⚖️ <b>Risk/Reward:</b> 1:{risk_reward:.2f}

🆔 <b>Order ID:</b> {order_id}
⏰ <b>Время:</b> {self._get_current_time()}
"""
        
        return self.send_notification(message.strip())
    
    def notify_trade_closed(self, trade_result: Dict[str, Any]) -> bool:
        """
        Уведомление о закрытой сделке
        
        Args:
            trade_result: Результат закрытой сделки
            
        Returns:
            bool: True если уведомление отправлено
        """
        logger.info(f"Отправляем уведомление о закрытии сделки: {trade_result}")
        
        # Извлекаем данные результата
        profit = trade_result.get('profit') or 0 
        success = trade_result.get('success', False)
        trade_type = trade_result.get('trade_type', 'UNKNOWN')
        entry_price = trade_result.get('entry_price') or 0
        exit_price = trade_result.get('exit_price') or 0
        position_size = trade_result.get('position_size') or 0
        
        # Определяем тип закрытия и эмодзи
        if success:
            result_emoji = "✅"
            result_text = "ПРИБЫЛЬ"
            color_emoji = "🟢"
        else:
            result_emoji = "❌"
            result_text = "УБЫТОК"
            color_emoji = "🔴"
        
        close_type_text = {
            'TP': 'Take Profit',
            'SL': 'Stop Loss',
            'MANUAL': 'Ручное закрытие'
        }.get(trade_type, trade_type)
        
        message = f"""
{result_emoji} <b>СДЕЛКА ЗАКРЫТА</b>

{color_emoji} <b>Результат:</b> {result_text}
🔄 <b>Тип закрытия:</b> {close_type_text}

📊 <b>Цена входа:</b> ${entry_price:,.2f}
🎯 <b>Цена выхода:</b> ${exit_price:,.2f}
💵 <b>Размер позиции:</b> ${position_size:,.2f}

💰 <b>Прибыль/Убыток:</b> ${profit:,.2f}
📈 <b>ROI:</b> {(profit/position_size*100) if position_size > 0 else 0:.2f}%

⏰ <b>Время:</b> {self._get_current_time()}
"""
        
        return self.send_notification(message.strip())
    
    def notify_system_status(self, status: str, details: str = None) -> bool:
        """
        Уведомление о состоянии системы
        
        Args:
            status: Статус системы (started, stopped, error, etc.)
            details: Дополнительные детали
            
        Returns:
            bool: True если уведомление отправлено
        """
        logger.info(f"Отправляем уведомление о статусе системы: {status}")
        
        status_config = {
            'started': {'emoji': '🚀', 'title': 'СИСТЕМА ЗАПУЩЕНА'},
            'stopped': {'emoji': '⏹️', 'title': 'СИСТЕМА ОСТАНОВЛЕНА'},
            'error': {'emoji': '💥', 'title': 'СИСТЕМНАЯ ОШИБКА'},
            'warning': {'emoji': '⚠️', 'title': 'СИСТЕМНОЕ ПРЕДУПРЕЖДЕНИЕ'},
            'info': {'emoji': 'ℹ️', 'title': 'СИСТЕМНАЯ ИНФОРМАЦИЯ'}
        }
        
        config = status_config.get(status, {'emoji': '📋', 'title': f'СТАТУС: {status.upper()}'})
        
        message = f"""
{config['emoji']} <b>{config['title']}</b>

{details if details else 'Система работает в штатном режиме'}

⏰ <b>Время:</b> {self._get_current_time()}
"""
        
        return self.send_notification(message.strip())
    
    def _get_current_time(self) -> str:
        """
        Получение текущего времени в читаемом формате
        
        Returns:
            str: Текущее время
        """
        from datetime import datetime
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
