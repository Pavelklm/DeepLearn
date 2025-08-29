"""
Простая система логирования на русском языке
"""

import logging
import logging.handlers
from pathlib import Path
from datetime import datetime
from typing import Optional

from config.main_config import LOGGING_CONFIG, FILE_CONFIG


def setup_logger(name: str, level: Optional[str] = None) -> logging.Logger:
    """
    Настройка простого логгера на русском языке
    
    Args:
        name: Имя логгера
        level: Уровень логирования
    
    Returns:
        Настроенный логгер
    """
    # Создаем директорию для логов
    logs_dir = Path(FILE_CONFIG["logs_directory"])
    logs_dir.mkdir(exist_ok=True)
    
    # Уровень логирования
    log_level = level or LOGGING_CONFIG["level"]
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Создаем логгер
    logger = logging.getLogger(name)
    logger.setLevel(numeric_level)
    
    # Очищаем существующие обработчики
    logger.handlers.clear()
    
    # Простой русский форматтер
    formatter = logging.Formatter(
        fmt='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%H:%M:%S'
    )
    
    # Файл основных логов
    log_file = logs_dir / "scanner.log"
    file_handler = logging.handlers.RotatingFileHandler(
        filename=log_file,
        maxBytes=LOGGING_CONFIG["max_file_size"],
        backupCount=LOGGING_CONFIG["backup_count"],
        encoding='utf-8'
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Консольный вывод
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    # Файл ошибок
    error_file = logs_dir / "errors.log"
    error_handler = logging.handlers.RotatingFileHandler(
        filename=error_file,
        maxBytes=LOGGING_CONFIG["max_file_size"],
        backupCount=LOGGING_CONFIG["backup_count"],
        encoding='utf-8'
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    logger.addHandler(error_handler)
    
    return logger


def get_component_logger(component: str) -> logging.Logger:
    """
    Получить логгер для компонента
    
    Args:
        component: Название компонента
    
    Returns:
        Настроенный логгер
    """
    return setup_logger(f"scanner.{component}")


class SimpleLogger:
    """Простой русскоязычный логгер для компонентов"""
    
    def __init__(self, component: str):
        self.logger = get_component_logger(component)
        self.component = component
    
    def info(self, message: str, **kwargs):
        """Информационное сообщение"""
        if kwargs:
            details = ", ".join([f"{k}: {v}" for k, v in kwargs.items()])
            self.logger.info(f"{message} ({details})")
        else:
            self.logger.info(message)
    
    def debug(self, message: str, **kwargs):
        """Отладочное сообщение"""
        if kwargs:
            details = ", ".join([f"{k}: {v}" for k, v in kwargs.items()])
            self.logger.debug(f"{message} ({details})")
        else:
            self.logger.debug(message)
    
    def warning(self, message: str, **kwargs):
        """Предупреждение"""
        if kwargs:
            details = ", ".join([f"{k}: {v}" for k, v in kwargs.items()])
            self.logger.warning(f"{message} ({details})")
        else:
            self.logger.warning(message)
    
    def error(self, message: str, **kwargs):
        """Ошибка"""
        if kwargs:
            details = ", ".join([f"{k}: {v}" for k, v in kwargs.items()])
            self.logger.error(f"{message} ({details})")
        else:
            self.logger.error(message)
    
    def success(self, message: str, **kwargs):
        """Успешное выполнение (как info но с пометкой)"""
        self.info(f"✓ {message}", **kwargs)
    
    def start_operation(self, operation: str):
        """Начало операции"""
        self.info(f"Запуск: {operation}")
    
    def finish_operation(self, operation: str, duration: float = None, success: bool = True):
        """Завершение операции"""
        status = "успешно" if success else "с ошибкой"
        if duration:
            self.info(f"Завершено {status}: {operation} ({duration:.2f}с)")
        else:
            self.info(f"Завершено {status}: {operation}")
    
    def stats(self, title: str, **stats):
        """Вывод статистики"""
        stats_str = ", ".join([f"{k}: {v}" for k, v in stats.items()])
        self.info(f"Статистика {title}: {stats_str}")
    
    def order_event(self, event: str, symbol: str, usd_value: float = None, order_hash: str = None):
        """Событие с ордером"""
        details = [symbol]
        if usd_value:
            details.append(f"${usd_value:,.0f}")
        if order_hash:
            details.append(f"#{order_hash[:8]}")
        
        self.info(f"Ордер {event}: {' '.join(details)}")
    
    def api_call(self, exchange: str, method: str, symbol: str = None, success: bool = True, duration: float = None):
        """API вызов"""
        status = "OK" if success else "ОШИБКА"
        details = [exchange, method]
        if symbol:
            details.append(symbol)
        if duration:
            details.append(f"{duration:.2f}с")
        
        self.debug(f"API {status}: {' '.join(details)}")
    
    def pool_status(self, pool_name: str, orders_count: int, symbols_count: int = None):
        """Статус пула"""
        details = [f"ордеров: {orders_count}"]
        if symbols_count:
            details.append(f"символов: {symbols_count}")
        
        self.info(f"Пул {pool_name}: {', '.join(details)}")


# Предустановленные логгеры для основных компонентов
main_logger = SimpleLogger("main")
scanner_logger = SimpleLogger("scanner")  
pools_logger = SimpleLogger("pools")
observer_logger = SimpleLogger("observer") 
hot_pool_logger = SimpleLogger("hot_pool")
exchange_logger = SimpleLogger("exchange")
websocket_logger = SimpleLogger("websocket")
analytics_logger = SimpleLogger("analytics")


def log_system_start():
    """Логирование запуска системы"""
    main_logger.info("=" * 50)
    main_logger.info("🚀 ЗАПУСК СКАННЕРА БОЛЬШИХ ОРДЕРОВ")
    main_logger.info("=" * 50)


def log_system_stop():
    """Логирование остановки системы"""  
    main_logger.info("=" * 50)
    main_logger.info("🛑 ОСТАНОВКА СКАННЕРА")
    main_logger.info("=" * 50)


def log_scan_results(total_orders: int, symbols_count: int, duration: float):
    """Логирование результатов сканирования"""
    scanner_logger.success(f"Первичное сканирование завершено")
    scanner_logger.stats("сканирование", 
                        ордеров=total_orders,
                        символов=symbols_count, 
                        время=f"{duration:.1f}с")


def log_hot_pool_update(diamond_count: int, gold_count: int, basic_count: int):
    """Логирование обновления горячего пула"""
    hot_pool_logger.pool_status("горячий",
                               diamond_count + gold_count + basic_count)
    if diamond_count > 0:
        hot_pool_logger.info(f"💎 Diamond ордеров: {diamond_count}")


def log_order_transition(symbol: str, from_pool: str, to_pool: str, usd_value: float):
    """Логирование перехода ордера между пулами"""
    pools_logger.info(f"Переход ордера: {symbol} ${usd_value:,.0f} ({from_pool} → {to_pool})")


def log_exchange_connection(exchange: str, success: bool, symbols_count: int = None):
    """Логирование подключения к бирже"""
    if success:
        details = f"символов: {symbols_count}" if symbols_count else ""
        exchange_logger.success(f"Подключение к {exchange} ({details})")
    else:
        exchange_logger.error(f"Не удалось подключиться к {exchange}")


def log_websocket_client(action: str, client_type: str, clients_count: int):
    """Логирование WebSocket клиентов"""
    websocket_logger.info(f"WebSocket {action}: {client_type} (всего: {clients_count})")


def log_weight_calculation(symbol: str, algorithm: str, weight: float, category: str):
    """Логирование расчета весов (только в debug режиме)"""
    analytics_logger.debug(f"Вес {symbol}: {algorithm}={weight:.3f} → {category}")


def log_error_with_context(component: str, error: str, **context):
    """Логирование ошибки с контекстом"""
    logger = SimpleLogger(component)
    context_str = ", ".join([f"{k}: {v}" for k, v in context.items()]) if context else ""
    
    if context_str:
        logger.error(f"Ошибка: {error} | Контекст: {context_str}")
    else:
        logger.error(f"Ошибка: {error}")


# Утилиты для измерения производительности
class Timer:
    """Простой таймер для измерения времени операций"""
    
    def __init__(self, logger: SimpleLogger, operation: str):
        self.logger = logger
        self.operation = operation
        self.start_time = None
    
    def __enter__(self):
        self.start_time = datetime.now()
        self.logger.debug(f"Начало: {self.operation}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.start_time:
            duration = (datetime.now() - self.start_time).total_seconds()
            success = exc_type is None
            self.logger.finish_operation(self.operation, duration, success)
            
            if not success:
                self.logger.error(f"Ошибка в {self.operation}: {exc_val}")
