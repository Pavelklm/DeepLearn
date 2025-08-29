"""
Вспомогательные функции - утилиты общего назначения
"""

import asyncio
import hashlib
import json
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union, Callable
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from src.utils.logger import get_component_logger

logger = get_component_logger("helpers")


def generate_order_hash(symbol: str, price: float, quantity: float, side: str) -> str:
    """
    Генерировать хэш для ордера (стандартный метод по спецификации)
    
    Args:
        symbol: Торговая пара
        price: Цена ордера
        quantity: Количество
        side: Сторона ордера (ASK/BID)
        
    Returns:
        Хэш формата SYMBOL-12символов
    """
    hash_string = f"{symbol}{price}{quantity}{side}{datetime.now().isoformat()}"
    hash_value = hashlib.md5(hash_string.encode()).hexdigest()[:12]
    return f"{symbol[:6]}-{hash_value}"


def round_to_precision(value: float, precision: int) -> float:
    """
    Округлить число до заданной точности
    
    Args:
        value: Значение для округления
        precision: Количество знаков после запятой
        
    Returns:
        Округленное значение
    """
    if precision < 0:
        return value
    
    decimal_value = Decimal(str(value))
    rounded = decimal_value.quantize(Decimal(f"0.{'0' * precision}"), rounding=ROUND_HALF_UP)
    return float(rounded)


def calculate_distance_percent(price1: float, price2: float) -> float:
    """
    Рассчитать процентное расстояние между двумя ценами
    
    Args:
        price1: Первая цена
        price2: Вторая цена (базовая)
        
    Returns:
        Процентное расстояние
    """
    if price2 <= 0:
        return 0.0
    
    return abs(price1 - price2) / price2 * 100


def is_round_level(price: float, threshold: float = 0.02) -> bool:
    """
    Проверить, находится ли цена близко к психологическому уровню
    
    Args:
        price: Цена для проверки
        threshold: Порог близости в процентах (по умолчанию 2%)
        
    Returns:
        True если цена близко к круглому уровню
    """
    # Психологические уровни из спецификации
    round_numbers = [0.0001, 0.001, 0.01, 0.1, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0, 500.0, 1000.0]
    
    for base in round_numbers:
        # Проверяем различные масштабы
        for multiplier in [0.001, 0.01, 0.1, 1, 10, 100, 1000]:
            level = base * multiplier
            if level > 0 and abs(price - level) / level <= threshold:
                return True
    
    return False


def format_usd_value(value: float) -> str:
    """
    Форматировать USD стоимость для отображения
    
    Args:
        value: USD стоимость
        
    Returns:
        Отформатированная строка
    """
    if value >= 1000000:
        return f"${value/1000000:.2f}M"
    elif value >= 1000:
        return f"${value/1000:.1f}K"
    else:
        return f"${value:.2f}"


def safe_float(value: Any, default: float = 0.0) -> float:
    """
    Безопасное преобразование в float
    
    Args:
        value: Значение для преобразования
        default: Значение по умолчанию
        
    Returns:
        Float значение или default при ошибке
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    """
    Безопасное преобразование в int
    
    Args:
        value: Значение для преобразования
        default: Значение по умолчанию
        
    Returns:
        Int значение или default при ошибке
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def get_current_timestamp() -> str:
    """Получить текущий timestamp в ISO формате UTC"""
    return datetime.now(timezone.utc).isoformat()


def parse_timestamp(timestamp_str: str) -> Optional[datetime]:
    """
    Парсинг timestamp строки в datetime объект
    
    Args:
        timestamp_str: Строка с timestamp
        
    Returns:
        datetime объект или None при ошибке
    """
    try:
        if timestamp_str.endswith('Z'):
            timestamp_str = timestamp_str[:-1] + '+00:00'
        return datetime.fromisoformat(timestamp_str)
    except (ValueError, AttributeError):
        return None


def filter_symbols(symbols: List[str], excluded_suffixes: List[str] = None,
                  excluded_prefixes: List[str] = None) -> List[str]:
    """
    Фильтровать список символов по спецификации
    
    Args:
        symbols: Список символов
        excluded_suffixes: Исключаемые суффиксы (стейблкоины)
        excluded_prefixes: Исключаемые префиксы
        
    Returns:
        Отфильтрованный список символов
    """
    if not symbols:
        return []
    
    # Дефолтные исключения из спецификации
    if excluded_suffixes is None:
        excluded_suffixes = ["USDT", "BUSD", "USDC", "FDUSD"]
    
    if excluded_prefixes is None:
        excluded_prefixes = ["1000"]
    
    filtered = []
    
    for symbol in symbols:
        # Проверяем суффиксы
        exclude_by_suffix = any(symbol.endswith(suffix) for suffix in excluded_suffixes)
        
        # Проверяем префиксы
        exclude_by_prefix = any(symbol.startswith(prefix) for prefix in excluded_prefixes)
        
        if not exclude_by_suffix and not exclude_by_prefix:
            filtered.append(symbol)
    
    return filtered


async def safe_api_call(func: Callable, *args, max_retries: int = 3, 
                       delay: float = 1.0, **kwargs) -> Optional[Any]:
    """
    Безопасный вызов API функции с повторными попытками
    
    Args:
        func: Функция для вызова
        *args: Позиционные аргументы
        max_retries: Максимальное количество попыток
        delay: Задержка между попытками
        **kwargs: Именованные аргументы
        
    Returns:
        Результат функции или None при неудаче
    """
    for attempt in range(max_retries):
        try:
            if asyncio.iscoroutinefunction(func):
                result = await func(*args, **kwargs)
            else:
                result = func(*args, **kwargs)
            
            return result
            
        except Exception as e:
            logger.debug(f"API вызов неудачен (попытка {attempt + 1}/{max_retries}): {e}")
            
            if attempt < max_retries - 1:
                await asyncio.sleep(delay * (attempt + 1))  # Экспоненциальная задержка
            else:
                logger.error(f"API вызов провален после {max_retries} попыток: {e}")
    
    return None


def save_json_file(data: Dict, filepath: Union[str, Path], pretty: bool = True) -> bool:
    """
    Безопасное сохранение JSON файла с атомарной записью
    
    Args:
        data: Данные для сохранения
        filepath: Путь к файлу
        pretty: Форматировать JSON с отступами
        
    Returns:
        True если успешно сохранено
    """
    try:
        filepath = Path(filepath)
        filepath.parent.mkdir(parents=True, exist_ok=True)
        
        # Атомарная запись через временный файл
        temp_file = filepath.with_suffix('.tmp')
        
        with open(temp_file, 'w', encoding='utf-8') as f:
            if pretty:
                json.dump(data, f, indent=2, ensure_ascii=False)
            else:
                json.dump(data, f, ensure_ascii=False)
        
        # Перемещаем временный файл
        temp_file.replace(filepath)
        return True
        
    except Exception as e:
        logger.error(f"Ошибка сохранения JSON файла {filepath}: {e}")
        return False


def load_json_file(filepath: Union[str, Path]) -> Optional[Dict]:
    """
    Безопасная загрузка JSON файла
    
    Args:
        filepath: Путь к файлу
        
    Returns:
        Данные из файла или None при ошибке
    """
    try:
        filepath = Path(filepath)
        
        if not filepath.exists():
            return None
        
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
            
    except Exception as e:
        logger.error(f"Ошибка загрузки JSON файла {filepath}: {e}")
        return None


def calculate_percentile(values: List[float], percentile: float) -> float:
    """
    Рассчитать процентиль для списка значений
    
    Args:
        values: Список значений
        percentile: Процентиль (0-100)
        
    Returns:
        Значение процентиля
    """
    if not values:
        return 0.0
    
    sorted_values = sorted(values)
    k = (len(sorted_values) - 1) * percentile / 100
    f = int(k)
    c = k - f
    
    if f == len(sorted_values) - 1:
        return sorted_values[f]
    
    return sorted_values[f] * (1 - c) + sorted_values[f + 1] * c


def create_chunks(items: List[Any], chunk_size: int) -> List[List[Any]]:
    """
    Разбить список на части заданного размера
    
    Args:
        items: Список элементов
        chunk_size: Размер части
        
    Returns:
        Список частей
    """
    if chunk_size <= 0:
        return [items]
    
    chunks = []
    for i in range(0, len(items), chunk_size):
        chunks.append(items[i:i + chunk_size])
    
    return chunks


class RateLimiter:
    """Простой rate limiter для API запросов"""
    
    def __init__(self, max_calls: int, time_window: float):
        self.max_calls = max_calls
        self.time_window = time_window
        self.calls = []
    
    async def acquire(self):
        """Получить разрешение на выполнение запроса"""
        now = time.time()
        
        # Удаляем старые записи
        self.calls = [call_time for call_time in self.calls 
                     if now - call_time < self.time_window]
        
        # Проверяем лимит
        if len(self.calls) >= self.max_calls:
            sleep_time = self.time_window - (now - self.calls[0])
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)
                return await self.acquire()
        
        # Записываем новый вызов
        self.calls.append(now)


def validate_config_values(config: Dict, required_keys: List[str]) -> bool:
    """
    Валидация значений конфигурации
    
    Args:
        config: Словарь конфигурации
        required_keys: Обязательные ключи
        
    Returns:
        True если все обязательные ключи присутствуют
    """
    for key in required_keys:
        if key not in config:
            logger.error(f"Отсутствует обязательный параметр конфигурации: {key}")
            return False
    
    return True


def clamp(value: float, min_value: float, max_value: float) -> float:
    """
    Ограничить значение в заданном диапазоне
    
    Args:
        value: Значение
        min_value: Минимальное значение
        max_value: Максимальное значение
        
    Returns:
        Ограниченное значение
    """
    return max(min_value, min(max_value, value))


def get_symbol_base_quote(symbol: str) -> tuple[str, str]:
    """
    Извлечь базовую и котировочную валюту из символа
    
    Args:
        symbol: Торговый символ (например, BTCUSDT)
        
    Returns:
        Кортеж (базовая_валюта, котировочная_валюта)
    """
    # Список известных котировочных валют по убыванию длины
    quote_currencies = ["USDT", "BUSD", "USDC", "FDUSD", "BTC", "ETH", "BNB"]
    
    for quote in quote_currencies:
        if symbol.endswith(quote):
            base = symbol[:-len(quote)]
            if base:  # Убеждаемся что базовая валюта не пустая
                return base, quote
    
    # Если не смогли определить, возвращаем как есть
    return symbol, ""
