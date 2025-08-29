"""
Базовый класс для всех бирж
Определяет единый интерфейс для работы с различными биржами
"""

import asyncio
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import structlog

from src.utils.logger import get_component_logger


class BaseExchange(ABC):
    """
    Базовый абстрактный класс для всех бирж
    Все биржи должны наследоваться от этого класса и реализовывать его методы
    """
    
    def __init__(self, name: str, config: dict):
        """
        Инициализация базового класса биржи
        
        Args:
            name: Название биржи
            config: Конфигурация биржи
        """
        self.name = name
        self.config = config
        self.logger = get_component_logger(f"exchange.{name}")
        self.is_connected = False
        self.last_request_time = 0
        self.request_count = 0
        self.error_count = 0
        
        # Rate limiting
        self.min_request_interval = 1.0 / config.get("requests_per_second", 10)
        
    @abstractmethod
    async def connect(self) -> bool:
        """
        Подключение к API биржи
        
        Returns:
            True если подключение успешно, False иначе
        """
        pass
    
    @abstractmethod
    async def disconnect(self):
        """Отключение от API биржи"""
        pass
    
    @abstractmethod
    async def get_futures_pairs(self) -> List[str]:
        """
        Получить список фьючерсных торговых пар
        
        Returns:
            Список символов торговых пар
        """
        pass
    
    @abstractmethod
    async def get_24h_volume_stats(self, symbols: Optional[List[str]] = None) -> Dict[str, dict]:
        """
        Получить статистику 24-часового объема торгов
        
        Args:
            symbols: Список символов для запроса (None = все)
            
        Returns:
            Словарь {symbol: {volume, price_change, etc}}
        """
        pass
    
    @abstractmethod
    async def get_orderbook(self, symbol: str, depth: int = 20) -> Dict:
        """
        Получить стакан заявок для торговой пары
        
        Args:
            symbol: Торговая пара
            depth: Глубина стакана
            
        Returns:
            Словарь с bids и asks
        """
        pass
    
    @abstractmethod
    async def get_current_price(self, symbol: str) -> float:
        """
        Получить текущую цену торговой пары
        
        Args:
            symbol: Торговая пара
            
        Returns:
            Текущая цена
        """
        pass
    
    @abstractmethod
    async def get_volatility_data(self, symbol: str, timeframe: str = "1h") -> dict:
        """
        Получить данные о волатильности
        
        Args:
            symbol: Торговая пара
            timeframe: Временной интервал (1h, 24h)
            
        Returns:
            Словарь с данными о волатильности
        """
        pass
    
    # Общие методы (не абстрактные)
    
    async def wait_for_rate_limit(self):
        """Ожидание для соблюдения rate limit"""
        now = asyncio.get_event_loop().time()
        time_since_last = now - self.last_request_time
        
        if time_since_last < self.min_request_interval:
            await asyncio.sleep(self.min_request_interval - time_since_last)
        
        self.last_request_time = asyncio.get_event_loop().time()
        self.request_count += 1
    
    def log_api_call(self, endpoint: str, symbol: str = None, success: bool = True, 
                     response_time: float = None):
        """
        Логирование API вызовов
        
        Args:
            endpoint: Конечная точка API
            symbol: Торговая пара (опционально)
            success: Успешность вызова
            response_time: Время ответа в секундах
        """
        if not success:
            self.error_count += 1
            
        status = "OK" if success else "ERROR"
        details = [endpoint]
        if symbol:
            details.append(symbol)
        if response_time:
            details.append(f"{response_time:.3f}s")
            
        self.logger.info(f"API {status}: {' '.join(details)} (total: {self.request_count}, errors: {self.error_count})")
    
    def get_stats(self) -> dict:
        """
        Получить статистику работы с биржей
        
        Returns:
            Словарь со статистикой
        """
        return {
            "name": self.name,
            "is_connected": self.is_connected,
            "total_requests": self.request_count,
            "error_count": self.error_count,
            "error_rate": self.error_count / max(self.request_count, 1),
            "last_request_time": self.last_request_time
        }
    
    def validate_symbol(self, symbol: str) -> bool:
        """
        Проверка корректности символа торговой пары
        
        Args:
            symbol: Символ для проверки
            
        Returns:
            True если символ корректный
        """
        if not symbol or not isinstance(symbol, str):
            return False
        
        # Базовая проверка формата
        if len(symbol) < 5 or len(symbol) > 20:
            return False
        
        # Проверка на исключенные суффиксы (если настроено)
        excluded_suffixes = self.config.get("excluded_suffixes", [])
        for suffix in excluded_suffixes:
            if symbol.endswith(suffix):
                return False
        
        return True
    
    async def retry_on_failure(self, coro, max_retries: int = 3, delay: float = 1.0):
        """
        Повторить выполнение корутины при неудаче
        
        Args:
            coro: Корутина для выполнения
            max_retries: Максимальное количество повторов
            delay: Задержка между повторами
            
        Returns:
            Результат выполнения корутины
            
        Raises:
            Exception: Если все попытки неудачны
        """
        last_exception = None
        
        for attempt in range(max_retries + 1):
            try:
                return await coro
            except Exception as e:
                last_exception = e
                
                if attempt < max_retries:
                    self.logger.warning(f"API call failed (attempt {attempt + 1}/{max_retries}), retrying: {str(e)}")
                    await asyncio.sleep(delay * (2 ** attempt))  # Экспоненциальная задержка
                else:
                    self.logger.error(f"API call failed after {max_retries} retries: {str(e)}")
        
        raise last_exception
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}(name='{self.name}', connected={self.is_connected})>"
