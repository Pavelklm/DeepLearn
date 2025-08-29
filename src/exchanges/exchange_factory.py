"""
Фабрика для создания экземпляров бирж
"""

import os
from typing import Dict, List, Optional
from dotenv import load_dotenv

from src.exchanges.base_exchange import BaseExchange
from src.exchanges.binance_api import BinanceAPI
from config.exchange_config import SUPPORTED_EXCHANGES
from src.utils.logger import get_component_logger

# Загружаем переменные окружения
load_dotenv()

logger = get_component_logger("exchange_factory")

# Функция валидации должна быть доступна для импорта
def validate_exchange_credentials(exchange_name: str) -> bool:
    """
    Проверить наличие учетных данных для биржи
    
    Args:
        exchange_name: Название биржи
        
    Returns:
        True если учетные данные найдены
    """
    if exchange_name.lower() == "binance":
        api_key = os.getenv("BINANCE_API_KEY")
        secret_key = os.getenv("BINANCE_SECRET_KEY")
        return bool(api_key and secret_key)
    
    elif exchange_name.lower() == "bybit":
        api_key = os.getenv("BYBIT_API_KEY")
        secret_key = os.getenv("BYBIT_SECRET_KEY")
        return bool(api_key and secret_key)
    
    return False


class ExchangeFactory:
    """
    Фабрика для создания и управления экземплярами бирж
    """
    
    def __init__(self):
        self.exchanges: Dict[str, BaseExchange] = {}
        self.logger = logger
    
    def create_exchange(self, exchange_name: str, testnet: bool = False) -> Optional[BaseExchange]:
        """
        Создать экземпляр биржи
        
        Args:
            exchange_name: Название биржи (binance, bybit, etc.)
            testnet: Использовать тестовую сеть
            
        Returns:
            Экземпляр биржи или None если биржа не поддерживается
        """
        exchange_name = exchange_name.lower()
        
        if exchange_name not in SUPPORTED_EXCHANGES:
            self.logger.error(f"Unsupported exchange: {exchange_name}")
            return None
        
        config = SUPPORTED_EXCHANGES[exchange_name]
        
        if not config["enabled"]:
            self.logger.warning(f"Exchange disabled in config: {exchange_name}")
            return None
        
        try:
            if exchange_name == "binance":
                return self._create_binance_exchange(testnet)
            
            elif exchange_name == "bybit":
                # TODO: Реализовать когда будет готов BybitAPI
                self.logger.error("Bybit API not implemented yet")
                return None
            
            else:
                self.logger.error(f"Unknown exchange implementation: {exchange_name}")
                return None
                
        except Exception as e:
            self.logger.error(f"Failed to create exchange {exchange_name}: {str(e)}")
            return None
    
    def _create_binance_exchange(self, testnet: bool = False) -> Optional[BinanceAPI]:
        """
        Создать экземпляр Binance API
        
        Args:
            testnet: Использовать тестовую сеть
            
        Returns:
            Экземпляр BinanceAPI или None если нет ключей
        """
        # Получаем API ключи из переменных окружения
        api_key = os.getenv("BINANCE_API_KEY")
        secret_key = os.getenv("BINANCE_SECRET_KEY")
        
        if not api_key or not secret_key:
            self.logger.error("Binance API keys not found in environment variables")
            self.logger.info("Please set BINANCE_API_KEY and BINANCE_SECRET_KEY in .env file")
            return None
        
        return BinanceAPI(api_key=api_key, secret_key=secret_key, testnet=testnet)
    
    async def get_or_create_exchange(self, exchange_name: str, testnet: bool = False) -> Optional[BaseExchange]:
        """
        Получить существующий или создать новый экземпляр биржи
        
        Args:
            exchange_name: Название биржи
            testnet: Использовать тестовую сеть
            
        Returns:
            Экземпляр биржи
        """
        cache_key = f"{exchange_name}{'_testnet' if testnet else ''}"
        
        # Проверяем кэш
        if cache_key in self.exchanges:
            exchange = self.exchanges[cache_key]
            # Проверяем что подключение активно
            if exchange.is_connected:
                return exchange
            else:
                # Пытаемся переподключиться
                try:
                    await exchange.connect()
                    if exchange.is_connected:
                        return exchange
                except Exception as e:
                    self.logger.warning(f"Failed to reconnect cached exchange {exchange_name}: {str(e)}")
        
        # Создаем новый экземпляр
        exchange = self.create_exchange(exchange_name, testnet)
        if not exchange:
            return None
        
        # Подключаемся
        try:
            connected = await exchange.connect()
            if connected:
                self.exchanges[cache_key] = exchange
                self.logger.info(f"Created and connected new exchange: {exchange_name} (testnet={testnet})")
                return exchange
            else:
                self.logger.error(f"Failed to connect new exchange: {exchange_name}")
                return None
                
        except Exception as e:
            self.logger.error(f"Exception while connecting new exchange {exchange_name}: {str(e)}")
            return None
    
    async def disconnect_all(self):
        """Отключить все биржи"""
        for exchange in self.exchanges.values():
            try:
                await exchange.disconnect()
            except Exception as e:
                self.logger.error(f"Error disconnecting exchange {exchange.name}: {str(e)}")
        
        self.exchanges.clear()
        self.logger.info("All exchanges disconnected")
    
    def get_supported_exchanges(self) -> List[str]:
        """
        Получить список поддерживаемых бирж
        
        Returns:
            Список названий поддерживаемых бирж
        """
        return [name for name, config in SUPPORTED_EXCHANGES.items() if config["enabled"]]
    
    def get_exchange_stats(self) -> Dict[str, dict]:
        """
        Получить статистику всех активных бирж
        
        Returns:
            Словарь со статистикой по каждой бирже
        """
        stats = {}
        for cache_key, exchange in self.exchanges.items():
            stats[cache_key] = exchange.get_stats()
        
        return stats


# Глобальный экземпляр фабрики
exchange_factory = ExchangeFactory()


async def get_binance_exchange(testnet: bool = False) -> Optional[BinanceAPI]:
    """
    Быстрый доступ к Binance API
    
    Args:
        testnet: Использовать тестовую сеть
        
    Returns:
        Экземпляр BinanceAPI
    """
    return await exchange_factory.get_or_create_exchange("binance", testnet)


async def get_exchange(exchange_name: str, testnet: bool = False) -> Optional[BaseExchange]:
    """
    Универсальный доступ к любой бирже
    
    Args:
        exchange_name: Название биржи
        testnet: Использовать тестовую сеть
        
    Returns:
        Экземпляр биржи
    """
    return await exchange_factory.get_or_create_exchange(exchange_name, testnet)

