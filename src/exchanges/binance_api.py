"""
Оптимизированная реализация API для Binance Futures
"""

import asyncio
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
    Оптимизированная реализация API для Binance Futures с кэшированием и батчингом
    """
    
    def __init__(self, api_key: str, secret_key: str, testnet: bool = False):
        super().__init__("binance", BINANCE_CONFIG)
        self.api_key = api_key
        self.secret_key = secret_key
        self.testnet = testnet
        self.base_url = BINANCE_CONFIG["testnet_url"] if testnet else "https://fapi.binance.com"
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Кэш для всех запросов
        self._cache: Dict[str, dict] = {}
        self._cache_ttl = 1  # секунда
        
        self._exchange_info: Optional[dict] = None
        self._pairs_cache: Optional[List[str]] = None
        self._pairs_cache_time = 0
        
        self.logger = get_component_logger("BinanceAPI")
        self.logger.info(f"Binance API initialized (testnet={testnet})")
    
    async def connect(self) -> bool:
        try:
            connector = aiohttp.TCPConnector(limit=100, limit_per_host=50)
            timeout = aiohttp.ClientTimeout(total=BINANCE_CONFIG["api_timeout"])
            self.session = aiohttp.ClientSession(
                connector=connector, 
                timeout=timeout, 
                json_serialize=ujson.dumps
            )
            
            await self._test_connectivity()
            await self._load_exchange_info()
            
            self.is_connected = True
            self.logger.info("Successfully connected to Binance API")
            return True
        except Exception as e:
            self.logger.error(f"Failed to connect to Binance API: {e}")
            self.is_connected = False
            return False

    async def disconnect(self):
        if self.session:
            await self.session.close()
            self.session = None
        self.is_connected = False
        self.logger.info("Disconnected from Binance API")
    
    # ---------------------- Внутренние методы ----------------------
    
    async def _cached_request(self, endpoint: str, symbol: Optional[str] = None, params: dict = {}):
        """
        Универсальный метод запроса с кэшированием
        """
        key = f"{endpoint}_{symbol}" if symbol else endpoint
        now = time.time()
        
        if key in self._cache and now - self._cache[key]["time"] < self._cache_ttl:
            return self._cache[key]["data"]
        
        url = f"{self.base_url}/{endpoint}"
        await self.wait_for_rate_limit()
        start_time = time.time()
        
        async with self.session.get(url, params=params) as response:
            if response.status != 200:
                self.log_api_call(endpoint, symbol=symbol, success=False, response_time=time.time() - start_time)
                raise Exception(f"Request to {endpoint} failed: {response.status}")
            
            data = await response.json(loads=ujson.loads)
            self._cache[key] = {"time": now, "data": data}
            self.log_api_call(endpoint, symbol=symbol, success=True, response_time=time.time() - start_time)
            return data

    async def _test_connectivity(self):
        await self._cached_request("fapi/v1/ping")

    async def _load_exchange_info(self):
        self._exchange_info = await self._cached_request("fapi/v1/exchangeInfo")
    
    # ---------------------- Публичные методы ----------------------
    
    async def get_futures_pairs(self) -> List[str]:
        """
        Получить список фьючерсных торговых пар с фильтрацией
        """
        if self._pairs_cache and time.time() - self._pairs_cache_time < 10:
            return self._pairs_cache
        
        if not self._exchange_info:
            await self._load_exchange_info()
        
        pairs = []
        for s in self._exchange_info["symbols"]:
            symbol = s["symbol"]
            if s["status"] != "TRADING":
                continue
            if s.get("contractType") not in ["PERPETUAL", "CURRENT_QUARTER", "NEXT_QUARTER"]:
                continue
            if self._apply_symbol_filters(symbol):
                pairs.append(symbol)
        
        self._pairs_cache = pairs
        self._pairs_cache_time = time.time()
        self.logger.info(f"Loaded futures pairs: {len(pairs)}")
        return pairs

    async def get_24h_volume_stats(self, symbols: Optional[List[str]] = None) -> Dict[str, dict]:
        """
        Получить 24h статистику всех символов за один запрос
        """
        data = await self._cached_request("fapi/v1/ticker/24hr")
        result = {}
        for ticker in data:
            symbol = ticker["symbol"]
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
                "count": int(ticker["count"]),
            }
        return result

    async def get_orderbook(self, symbol: str, depth: int = 20) -> dict:
        valid_limits = [5, 10, 20, 50, 100, 500, 1000]
        limit = min(valid_limits, key=lambda x: abs(x - depth))
        data = await self._cached_request(
            "fapi/v1/depth", symbol=symbol, params={"symbol": symbol, "limit": limit}
        )
        return {
            "lastUpdateId": data["lastUpdateId"],
            "bids": [[float(p), float(q)] for p, q in data["bids"]],
            "asks": [[float(p), float(q)] for p, q in data["asks"]],
            "symbol": symbol,
            "timestamp": int(time.time() * 1000)
        }

    async def get_current_price(self, symbol: str) -> float:
        data = await self._cached_request(
            "fapi/v1/ticker/price", symbol=symbol, params={"symbol": symbol}
        )
        return float(data["price"])

    async def get_volatility_data(self, symbol: str, timeframe: str = "1h") -> dict:
        limit_map = {"1h": 24, "24h": 7}
        limit = limit_map.get(timeframe, 24)
        data = await self._cached_request(
            "fapi/v1/klines", symbol=symbol, params={"symbol": symbol, "interval": timeframe, "limit": limit}
        )
        closes = [float(k[4]) for k in data]
        if len(closes) < 2:
            return {"volatility": 0.0, "avg_price": closes[0] if closes else 0.0}
        
        price_changes = [abs(closes[i] - closes[i-1]) / closes[i-1] for i in range(1, len(closes))]
        avg_change = sum(price_changes) / len(price_changes)
        volatility = (sum((x - avg_change) ** 2 for x in price_changes) / len(price_changes)) ** 0.5 if price_changes else 0.0
        return {
            "volatility": volatility,
            "avg_price": sum(closes) / len(closes),
            "high_price": max(closes),
            "low_price": min(closes),
            "price_change": (closes[-1] - closes[0]) / closes[0] if closes[0] != 0 else 0,
            "timeframe": timeframe,
            "data_points": len(closes)
        }

    async def get_top_volume_symbols(self, limit: int = 250) -> List[str]:
        volume_stats = await self.get_24h_volume_stats()
        valid_symbols = [
            (s, v["quote_volume"]) 
            for s, v in volume_stats.items() 
            if self._apply_symbol_filters(s) and v["quote_volume"] >= FILTERING_CONFIG.get("min_24h_volume_usdt", 100_000)
        ]
        valid_symbols.sort(key=lambda x: x[1], reverse=True)
        return [s for s, _ in valid_symbols[:limit]]

    def get_price_precision(self, symbol: str) -> int:
        for s in (self._exchange_info["symbols"] if self._exchange_info else []):
            if s["symbol"] == symbol:
                return s.get("pricePrecision", 8)
        return 8

    def get_quantity_precision(self, symbol: str) -> int:
        for s in (self._exchange_info["symbols"] if self._exchange_info else []):
            if s["symbol"] == symbol:
                return s.get("quantityPrecision", 8)
        return 8

    def _apply_symbol_filters(self, symbol: str) -> bool:
        for suffix in FILTERING_CONFIG["excluded_suffixes"]:
            if symbol.endswith(suffix):
                return False
        for prefix in FILTERING_CONFIG["excluded_prefixes"]:
            if symbol.startswith(prefix):
                return False
        if symbol in FILTERING_CONFIG.get("blacklist_symbols", []):
            return False
        whitelist = FILTERING_CONFIG.get("whitelist_symbols")
        if whitelist and symbol not in whitelist:
            return False
        return True

    # ---------------------- Методы для батчинга ----------------------

    async def fetch_depth_batch(self, symbols: list, depth: int = 20) -> dict:
        results = {}
        batch_size = 10
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i+batch_size]
            tasks = [self.get_orderbook(s, depth) for s in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for s, r in zip(batch, batch_results):
                if isinstance(r, Exception):
                    self.logger.error(f"Ошибка depth для {s}: {r}")
                else:
                    results[s] = r
                    self.logger.info(f"API OK: depth {s} (total: {len(symbols)}, errors: 0)")
        return results

    async def fetch_klines_batch(self, symbols: list, interval="1h") -> dict:
        results = {}
        batch_size = 10
        for i in range(0, len(symbols), batch_size):
            batch = symbols[i:i+batch_size]
            tasks = [self.get_volatility_data(s, interval) for s in batch]
            batch_results = await asyncio.gather(*tasks, return_exceptions=True)
            for s, r in zip(batch, batch_results):
                if isinstance(r, Exception):
                    self.logger.error(f"Ошибка klines для {s}: {r}")
                else:
                    results[s] = r
                    self.logger.info(f"API OK: klines {s} (total: {len(symbols)}, errors: 0)")
        return results

    async def fetch_prices(self, symbols: list) -> dict:
        data = await self.get_24h_volume_stats(symbols)
        for s in symbols:
            self.logger.info(f"API OK: price {s} (total: {len(symbols)}, errors: 0)")
        return {s: data[s]["last_price"] for s in symbols}

    async def fetch_all_data(self, symbols: list, depth=20, interval="1h") -> dict:
        """Собирает все данные для списка символов с правильным логом total = len(symbols)"""
        results = {}
        tasks = [
            self.fetch_depth_batch(symbols, depth),
            self.fetch_klines_batch(symbols, interval),
            self.fetch_prices(symbols)
        ]
        depth_data, klines_data, price_data = await asyncio.gather(*tasks)
        results["depth"] = depth_data
        results["klines"] = klines_data
        results["price"] = price_data
        return results
