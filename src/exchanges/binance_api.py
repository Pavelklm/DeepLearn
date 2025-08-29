"""
Реализация API для Binance Futures
"""

import asyncio
import hmac
import hashlib
import time
import aiohttp
import ujson
from typing import Dict, List, Optional
from urllib.parse import urlencode

from src.exchanges.base_exchange import BaseExchange
from config.exchange_config import BINANCE_CONFIG, FILTERING_CONFIG
from src.utils.logger import get_component_logger


class BinanceAPI(BaseExchange):
    """
    Реализация API для Binance Futures
    """
    
    def __init__(self, api_key: str, secret_key: str, testnet: bool = False):
        """
        Инициализация Binance API
        
        Args:
            api_key: API ключ Binance
            secret_key: Секретный ключ Binance
            testnet: Использовать testnet (по умолчанию False)
        """
        super().__init__("binance", BINANCE_CONFIG)
        
        self.api_key = api_key
        self.secret_key = secret_key
        self.testnet = testnet
        
        # Определяем базовый URL
        if testnet:
            self.base_url = BINANCE_CONFIG["testnet_url"]
        else:
            self.base_url = "https://fapi.binance.com"
            
        self.session = None
        
        # Кэш для данных
        self._pairs_cache = None
        self._pairs_cache_time = 0
        self._exchange_info = None
        
        self.logger.info("Binance API initialized", testnet=testnet)
    
    async def connect(self) -> bool:
        """
        Подключение к Binance API
        
        Returns:
            True если подключение успешно
        """
        try:
            # Создаем HTTP сессию
            connector = aiohttp.TCPConnector(limit=100, limit_per_host=50)
            timeout = aiohttp.ClientTimeout(total=BINANCE_CONFIG["api_timeout"])
            
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout,
                json_serialize=ujson.dumps
            )
            
            # Проверяем подключение запросом к серверу
            await self._test_connectivity()
            
            # Получаем информацию о парах
            await self._load_exchange_info()
            
            self.is_connected = True
            self.logger.info("Successfully connected to Binance API")
            return True
            
        except Exception as e:
            self.logger.error("Failed to connect to Binance API", error=str(e))
            self.is_connected = False
            return False
    
    async def disconnect(self):
        """Отключение от Binance API"""
        if self.session:
            await self.session.close()
            self.session = None
        
        self.is_connected = False
        self.logger.info("Disconnected from Binance API")
    
    async def _test_connectivity(self):
        """Тестирование подключения к API"""
        url = f"{self.base_url}/fapi/v1/ping"
        
        async with self.session.get(url) as response:
            if response.status != 200:
                raise Exception(f"Ping failed with status {response.status}")
    
    async def _load_exchange_info(self):
        """Загрузка информации о торговых парах"""
        url = f"{self.base_url}/fapi/v1/exchangeInfo"
        
        start_time = time.time()
        await self.wait_for_rate_limit()
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    self._exchange_info = await response.json(loads=ujson.loads)
                    response_time = time.time() - start_time
                    self.log_api_call("exchangeInfo", success=True, response_time=response_time)
                else:
                    raise Exception(f"Exchange info request failed: {response.status}")
                    
        except Exception as e:
            self.log_api_call("exchangeInfo", success=False, response_time=time.time() - start_time)
            raise
    
    async def get_futures_pairs(self) -> List[str]:
        """
        Получить список фьючерсных торговых пар
        
        Returns:
            Отфильтрованный список торговых пар
        """
        if not self._exchange_info:
            await self._load_exchange_info()
        
        pairs = []
        
        for symbol_info in self._exchange_info["symbols"]:
            symbol = symbol_info["symbol"]
            
            # Проверяем статус торговли
            if symbol_info["status"] != "TRADING":
                continue
            
            # Проверяем что это фьючерс (включаем все типы контрактов)
            # PERPETUAL - бессрочные фьючерсы, CURRENT_QUARTER - квартальные
            if symbol_info.get("contractType") not in ["PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER"]:
                continue
            
            # Применяем фильтры
            if self._apply_symbol_filters(symbol):
                pairs.append(symbol)
        
        self.logger.info("Loaded futures pairs", total_pairs=len(pairs))
        return pairs
    
    def _apply_symbol_filters(self, symbol: str) -> bool:
        """
        Применение фильтров к символу торговой пары
        
        Args:
            symbol: Символ торговой пары
            
        Returns:
            True если символ проходит все фильтры
        """
        # Исключаем стейблкоины
        for suffix in FILTERING_CONFIG["excluded_suffixes"]:
            if symbol.endswith(suffix):
                return False
        
        # Исключаем префиксы
        for prefix in FILTERING_CONFIG["excluded_prefixes"]:
            if symbol.startswith(prefix):
                return False
        
        # Проверяем черный список
        if symbol in FILTERING_CONFIG.get("blacklist_symbols", []):
            return False
        
        # Проверяем белый список (если настроен)
        whitelist = FILTERING_CONFIG.get("whitelist_symbols")
        if whitelist and symbol not in whitelist:
            return False
        
        return True
    
    async def get_24h_volume_stats(self, symbols: Optional[List[str]] = None) -> Dict[str, dict]:
        """
        Получить статистику 24-часового объема торгов
        
        Args:
            symbols: Список символов (если None - все символы)
            
        Returns:
            Словарь {symbol: {volume, quoteVolume, priceChange, etc}}
        """
        url = f"{self.base_url}/fapi/v1/ticker/24hr"
        
        start_time = time.time()
        await self.wait_for_rate_limit()
        
        try:
            async with self.session.get(url) as response:
                if response.status == 200:
                    data = await response.json(loads=ujson.loads)
                    response_time = time.time() - start_time
                    self.log_api_call("ticker/24hr", success=True, response_time=response_time)
                    
                    # Преобразуем в удобный формат
                    result = {}
                    for ticker in data:
                        symbol = ticker["symbol"]
                        
                        # Фильтруем символы если нужно
                        if symbols and symbol not in symbols:
                            continue
                        
                        result[symbol] = {
                            "volume": float(ticker["volume"]),
                            "quote_volume": float(ticker["quoteVolume"]),
                            "price_change": float(ticker["priceChange"]),
                            "price_change_percent": float(ticker["priceChangePercent"]),
                            "last_price": float(ticker["lastPrice"]),
                            "high_price": float(ticker["highPrice"]),
                            "low_price": float(ticker["lowPrice"]),
                            "open_price": float(ticker["openPrice"]),
                            "count": int(ticker["count"])
                        }
                    
                    return result
                    
                else:
                    raise Exception(f"24hr ticker request failed: {response.status}")
                    
        except Exception as e:
            self.log_api_call("ticker/24hr", success=False, response_time=time.time() - start_time)
            raise
    
    async def get_orderbook(self, symbol: str, depth: int = 20) -> Dict:
        """
        Получить стакан заявок для торговой пары
        
        Args:
            symbol: Торговая пара
            depth: Глубина стакана
            
        Returns:
            Словарь с bids и asks, lastUpdateId
        """
        if not self.validate_symbol(symbol):
            raise ValueError(f"Invalid symbol: {symbol}")
        
        # Binance поддерживает лимиты: 5, 10, 20, 50, 100, 500, 1000
        valid_limits = [5, 10, 20, 50, 100, 500, 1000]
        limit = min(valid_limits, key=lambda x: abs(x - depth))
        
        url = f"{self.base_url}/fapi/v1/depth"
        params = {"symbol": symbol, "limit": limit}
        
        start_time = time.time()
        await self.wait_for_rate_limit()
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json(loads=ujson.loads)
                    response_time = time.time() - start_time
                    self.log_api_call("depth", symbol=symbol, success=True, response_time=response_time)
                    
                    # Преобразуем строки в числа
                    result = {
                        "lastUpdateId": data["lastUpdateId"],
                        "bids": [[float(price), float(qty)] for price, qty in data["bids"]],
                        "asks": [[float(price), float(qty)] for price, qty in data["asks"]],
                        "symbol": symbol,
                        "timestamp": int(time.time() * 1000)
                    }
                    
                    return result
                    
                else:
                    raise Exception(f"Orderbook request failed: {response.status}")
                    
        except Exception as e:
            self.log_api_call("depth", symbol=symbol, success=False, response_time=time.time() - start_time)
            raise
    
    async def get_current_price(self, symbol: str) -> float:
        """
        Получить текущую цену торговой пары
        
        Args:
            symbol: Торговая пара
            
        Returns:
            Текущая цена
        """
        url = f"{self.base_url}/fapi/v1/ticker/price"
        params = {"symbol": symbol}
        
        start_time = time.time()
        await self.wait_for_rate_limit()
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json(loads=ujson.loads)
                    response_time = time.time() - start_time
                    self.log_api_call("ticker/price", symbol=symbol, success=True, response_time=response_time)
                    
                    return float(data["price"])
                    
                else:
                    raise Exception(f"Price request failed: {response.status}")
                    
        except Exception as e:
            self.log_api_call("ticker/price", symbol=symbol, success=False, response_time=time.time() - start_time)
            raise
    
    async def get_volatility_data(self, symbol: str, timeframe: str = "1h") -> dict:
        """
        Получить данные о волатильности на основе klines
        
        Args:
            symbol: Торговая пара
            timeframe: Временной интервал (1h, 24h)
            
        Returns:
            Словарь с данными о волатильности
        """
        # Определяем количество свечей для анализа
        limit_map = {"1h": 24, "24h": 7}  # 24 часа для 1h, 7 дней для 24h
        limit = limit_map.get(timeframe, 24)
        
        url = f"{self.base_url}/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": timeframe,
            "limit": limit
        }
        
        start_time = time.time()
        await self.wait_for_rate_limit()
        
        try:
            async with self.session.get(url, params=params) as response:
                if response.status == 200:
                    data = await response.json(loads=ujson.loads)
                    response_time = time.time() - start_time
                    self.log_api_call("klines", symbol=symbol, success=True, response_time=response_time)
                    
                    # Рассчитываем волатильность
                    closes = [float(kline[4]) for kline in data]  # Цены закрытия
                    
                    if len(closes) < 2:
                        return {"volatility": 0.0, "avg_price": closes[0] if closes else 0.0}
                    
                    # Простой расчет волатильности как стандартное отклонение изменений цен
                    price_changes = []
                    for i in range(1, len(closes)):
                        change = abs(closes[i] - closes[i-1]) / closes[i-1]
                        price_changes.append(change)
                    
                    if price_changes:
                        avg_change = sum(price_changes) / len(price_changes)
                        volatility = (sum((x - avg_change) ** 2 for x in price_changes) / len(price_changes)) ** 0.5
                    else:
                        volatility = 0.0
                    
                    return {
                        "volatility": volatility,
                        "avg_price": sum(closes) / len(closes),
                        "high_price": max(closes),
                        "low_price": min(closes),
                        "price_change": (closes[-1] - closes[0]) / closes[0] if closes[0] != 0 else 0,
                        "timeframe": timeframe,
                        "data_points": len(closes)
                    }
                    
                else:
                    raise Exception(f"Klines request failed: {response.status}")
                    
        except Exception as e:
            self.log_api_call("klines", symbol=symbol, success=False, response_time=time.time() - start_time)
            raise
    
    async def get_top_volume_symbols(self, limit: int = 250) -> List[str]:
        """
        Получить топ символов по объему торгов за 24h
        
        Args:
            limit: Количество символов для возврата
            
        Returns:
            Список символов, отсортированных по убыванию объема
        """
        volume_stats = await self.get_24h_volume_stats()
        
        # Фильтруем и сортируем по объему в USDT
        valid_symbols = []
        for symbol, stats in volume_stats.items():
            if self._apply_symbol_filters(symbol):
                # Проверяем минимальный объем
                if stats["quote_volume"] >= FILTERING_CONFIG.get("min_24h_volume_usdt", 100000):
                    valid_symbols.append((symbol, stats["quote_volume"]))
        
        # Сортируем по объему (убывание) и берем топ
        valid_symbols.sort(key=lambda x: x[1], reverse=True)
        top_symbols = [symbol for symbol, volume in valid_symbols[:limit]]
        
        self.logger.info("Selected top volume symbols", 
                        total_filtered=len(valid_symbols), 
                        selected=len(top_symbols))
        
        return top_symbols
    
    def get_price_precision(self, symbol: str) -> int:
        """
        Получить точность цены для символа
        
        Args:
            symbol: Торговая пара
            
        Returns:
            Количество знаков после запятой для цены
        """
        if not self._exchange_info:
            return 8  # Значение по умолчанию
        
        for symbol_info in self._exchange_info["symbols"]:
            if symbol_info["symbol"] == symbol:
                return symbol_info.get("pricePrecision", 8)
        
        return 8
    
    def get_quantity_precision(self, symbol: str) -> int:
        """
        Получить точность количества для символа
        
        Args:
            symbol: Торговая пара
            
        Returns:
            Количество знаков после запятой для количества
        """
        if not self._exchange_info:
            return 8
        
        for symbol_info in self._exchange_info["symbols"]:
            if symbol_info["symbol"] == symbol:
                return symbol_info.get("quantityPrecision", 8)
        
        return 8
    
    def _apply_symbol_filters(self, symbol: str) -> bool:
        """
        Применение фильтров к символу торговой пары
        
        Args:
            symbol: Символ торговой пары
            
        Returns:
            True если символ проходит все фильтры
        """
        # Исключаем стейблкоины
        for suffix in FILTERING_CONFIG["excluded_suffixes"]:
            if symbol.endswith(suffix):
                return False
        
        # Исключаем префиксы
        for prefix in FILTERING_CONFIG["excluded_prefixes"]:
            if symbol.startswith(prefix):
                return False
        
        # Проверяем черный список
        if symbol in FILTERING_CONFIG.get("blacklist_symbols", []):
            return False
        
        # Проверяем белый список (если настроен)
        whitelist = FILTERING_CONFIG.get("whitelist_symbols")
        if whitelist and symbol not in whitelist:
            return False
        
        return True
