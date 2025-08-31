"""
Первичный сканнер - выполняет одноразовое сканирование всех топ-монет
"""

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Optional, Set
from dataclasses import dataclass

from src.workers.base_worker import BaseWorker
from src.workers.adaptive_workers import AdaptiveWorkerManager
from src.exchanges.base_exchange import BaseExchange
from src.analytics.adaptive_categories import AdaptiveCategorizer
from config.main_config import PRIMARY_SCAN_CONFIG, FILTERING_CONFIG
from src.utils.logger import get_component_logger

logger = get_component_logger("primary_scanner")


@dataclass
class LargeOrder:
    """Структура большого ордера найденного при первичном сканировании"""
    symbol: str
    current_price: float
    order_type: str  # ASK или BID
    price: float
    quantity: float
    usd_value: float
    distance_percent: float
    size_vs_average: float
    average_order_size: float
    first_seen: datetime
    order_hash: str
    volatility_1h: float = 0.0
    scan_count: int = 1
    is_round_level: bool = False


class PrimaryScanner:
    """Первичный сканнер для поиска больших ордеров"""
    
    def __init__(self, exchange: BaseExchange, observer_pool=None):
        self.exchange = exchange
        self.observer_pool = observer_pool
        self.config = PRIMARY_SCAN_CONFIG
        self.logger = logger
        
        # Статистика
        self.scanned_symbols = 0
        self.total_large_orders = 0
        self.orders_by_symbol: Dict[str, int] = {}
        self.scan_start_time = None
        self.scan_end_time = None
        
        # Результаты сканирования
        self.found_orders: List[LargeOrder] = []
        
    def add_found_order(self, order: LargeOrder):
        """Добавление найденного большого ордера"""
        self.found_orders.append(order)
        self.total_large_orders += 1
        
        symbol = order.symbol
        if symbol not in self.orders_by_symbol:
            self.orders_by_symbol[symbol] = 0
        self.orders_by_symbol[symbol] += 1
        
        # Отправляем ордер в пул наблюдателя если он настроен
        if self.observer_pool:
            order_data = {
                "symbol": order.symbol,
                "price": order.price,
                "quantity": order.quantity,
                "type": order.order_type,
                "usd_value": order.usd_value,
                "distance_percent": order.distance_percent,
                "size_vs_average": order.size_vs_average,
                "average_order_size": order.average_order_size,
                "first_seen": order.first_seen.isoformat(),
                "volatility_1h": order.volatility_1h,
                "is_round_level": order.is_round_level,
                "order_hash": order.order_hash
            }
            self.observer_pool.add_order_from_primary_scan(order_data)
        
        self.logger.debug(f"Added large order: {order.symbol} ${order.usd_value:,.0f} #{order.order_hash}")
    
    def _get_scan_results(self) -> Dict:
        """Получение результатов сканирования с адаптивными категориями"""
        duration = 0
        if self.scan_start_time:
            end_time = self.scan_end_time or datetime.now(timezone.utc)
            duration = (end_time - self.scan_start_time).total_seconds()

        # Сортируем ордера по размеру (убывание)
        sorted_orders = sorted(self.found_orders, key=lambda x: x.usd_value, reverse=True)

        # --- Адаптивная категоризация ---
        categorizer = AdaptiveCategorizer()
        order_values = [order.usd_value for order in self.found_orders]
        adaptive_data = categorizer.calculate_adaptive_thresholds(order_values)

        # Преобразуем ордера в словари для категорий
        order_dicts = [self._order_to_dict(order) for order in self.found_orders]
        categories = categorizer.categorize_orders(order_dicts, adaptive_data)

        # --- Статистика ---
        stats = {
            "symbols_with_orders": len(self.orders_by_symbol),
            "round_level_orders": len([o for o in self.found_orders if o.is_round_level]),
            "max_usd_value": max([o.usd_value for o in self.found_orders], default=0),
            "min_usd_value": min([o.usd_value for o in self.found_orders], default=0),
            "avg_usd_value": (sum([o.usd_value for o in self.found_orders]) / len(self.found_orders)) if self.found_orders else 0
        }

        return {
            "scan_completed": True,
            "scan_start_time": self.scan_start_time.isoformat() if self.scan_start_time else None,
            "scan_end_time": self.scan_end_time.isoformat() if self.scan_end_time else None,
            "duration_seconds": duration,
            "total_symbols_scanned": self.scanned_symbols,
            "total_large_orders": self.total_large_orders,
            "orders_by_symbol": self.orders_by_symbol,
            "top_orders": order_dicts[:10],

            # Адаптивные категории
            "adaptive_categories": {
                "method": adaptive_data["method"],
                "thresholds": adaptive_data["thresholds"],
                "distribution": {
                    "diamond": len(categories["diamond"]),
                    "gold": len(categories["gold"]),
                    "basic": len(categories["basic"])
                },
                "categories": categories
            },

            # Статистика и перцентили
            "statistics": {
                **adaptive_data.get("stats", {}),
                "percentiles": adaptive_data.get("percentiles", {}),
                **stats
            }
    }
    
    def _order_to_dict(self, order: LargeOrder) -> Dict:
        """Преобразование ордера в словарь"""
        return {
            "symbol": order.symbol,
            "current_price": order.current_price,
            "type": order.order_type,
            "price": order.price,
            "quantity": order.quantity,
            "usd_value": order.usd_value,
            "distance_percent": order.distance_percent,
            "size_vs_average": order.size_vs_average,
            "volatility_1h": order.volatility_1h,
            "is_round_level": order.is_round_level,
            "first_seen": order.first_seen.isoformat(),
            "order_hash": order.order_hash
        }
    
    async def run_test_scan(self, symbols: List[str]) -> Dict:
        """Тестовое сканирование ограниченного количества символов"""
        self.logger.info(f"Starting test scan of {len(symbols)} symbols")
        self.scan_start_time = datetime.now(timezone.utc)
        
        try:
            for symbol in symbols:
                try:
                    # Сканируем символ
                    orderbook = await self.exchange.get_orderbook(symbol, depth=self.config["orderbook_depth"])
                    current_price = await self.exchange.get_current_price(symbol)
                    
                    # Получаем волатильность
                    try:
                        volatility_data = await self.exchange.get_volatility_data(symbol, "1h")
                        volatility_1h = volatility_data.get("volatility", 0.0)
                    except Exception:
                        volatility_1h = 0.0
                    
                    # Анализируем большие ордера
                    large_orders = []
                    
                    # ASKs (продажи)
                    if orderbook.get("asks"):
                        large_asks = self._find_large_orders_in_side_simple(
                            symbol, orderbook["asks"], current_price, "ASK", volatility_1h
                        )
                        large_orders.extend(large_asks)
                    
                    # BIDs (покупки) 
                    if orderbook.get("bids"):
                        large_bids = self._find_large_orders_in_side_simple(
                            symbol, orderbook["bids"], current_price, "BID", volatility_1h
                        )
                        large_orders.extend(large_bids)
                    
                    # Добавляем найденные ордера
                    for order in large_orders:
                        self.add_found_order(order)
                    
                    if large_orders:
                        self.logger.info(f"Found {len(large_orders)} large orders in {symbol}")
                    
                    self.scanned_symbols += 1
                    
                    # Небольшая задержка между символами
                    await asyncio.sleep(self.config.get("min_request_delay", 0.1))
                    
                except Exception as e:
                    self.logger.error(f"Error scanning symbol {symbol}: {str(e)}")
                    continue
            
            return self._get_scan_results()
            
        except Exception as e:
            self.logger.error(f"Error in test scan: {str(e)}")
            raise
        finally:
            self.scan_end_time = datetime.now(timezone.utc)
    
    def _find_large_orders_in_side_simple(self, symbol: str, orders: List, current_price: float,
                                          side_type: str, volatility_1h: float) -> List[LargeOrder]:
        """Упрощенный поиск больших ордеров для тестирования"""
        if len(orders) < 10:
            return []
        
        # Берем топ-10 и считаем среднее
        top_10 = orders[:10]
        total_volume = sum(float(price) * float(qty) for price, qty in top_10)
        average_volume = total_volume / 10
        
        # Порог для большого ордера
        large_threshold = average_volume * self.config["large_order_multiplier"]
        
        large_orders = []
        now = datetime.now(timezone.utc)
        
        for price, qty in orders:
            price_float = float(price)
            qty_float = float(qty)
            usd_value = price_float * qty_float
            
            if usd_value >= large_threshold:
                distance_percent = abs(price_float - current_price) / current_price * 100
                is_round_level = self._is_near_round_level(price_float)
                order_hash = self._generate_order_hash(symbol, price_float, qty_float, side_type)
                
                order = LargeOrder(
                    symbol=symbol,
                    current_price=current_price,
                    order_type=side_type,
                    price=price_float,
                    quantity=qty_float,
                    usd_value=usd_value,
                    distance_percent=distance_percent,
                    size_vs_average=usd_value / average_volume,
                    average_order_size=average_volume,
                    first_seen=now,
                    order_hash=order_hash,
                    volatility_1h=volatility_1h,
                    is_round_level=is_round_level
                )
                
                large_orders.append(order)
        
        return large_orders
    
    def _is_near_round_level(self, price: float, threshold: float = 0.001) -> bool:
        """Проверка близости к психологическому (круглому) уровню"""
        round_numbers = [0.1, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0, 500.0, 1000.0, 5000.0, 10000.0]
        
        for base in round_numbers:
            for multiplier in [0.001, 0.01, 0.1, 1, 10, 100, 1000]:
                level = base * multiplier
                if level > 0 and abs(price - level) / level <= threshold:
                    return True
        
        return False
    
    async def run_full_scan(self) -> Dict:
        self.logger.info("Starting full scan of top symbols")
        self.scan_start_time = datetime.now(timezone.utc)

        try:
            top_symbols = await self.exchange.get_top_volume_symbols(
                self.config["top_coins_limit"]
            )

            if not top_symbols:
                raise Exception("No symbols received for scanning")

            self.logger.info(f"Scanning {len(top_symbols)} symbols with {self.config['workers_count']} workers")

            # Разделяем символы между воркерами
            chunk_size = len(top_symbols) // self.config["workers_count"]
            symbol_chunks = []

            for i in range(self.config["workers_count"]):
                start_idx = i * chunk_size
                end_idx = len(top_symbols) if i == self.config["workers_count"] - 1 else start_idx + chunk_size
                if start_idx < len(top_symbols):
                    symbol_chunks.append(top_symbols[start_idx:end_idx])

            # Запускаем воркеров
            tasks = [asyncio.create_task(self._scan_symbol_chunk(chunk, i)) for i, chunk in enumerate(symbol_chunks)]
            await asyncio.gather(*tasks)

        except Exception as e:
            self.logger.error(f"Error in full scan: {str(e)}")
            raise
        finally:
            self.scan_end_time = datetime.now(timezone.utc)

        return self._get_scan_results()

    
    async def _scan_symbol_chunk(self, symbols: List[str], worker_id: int):
        """Сканирование группы символов одним воркером"""
        self.logger.debug(f"Worker {worker_id} started with {len(symbols)} symbols")
        for symbol in symbols:
            try:
                # Сканируем символ
                orderbook = await self.exchange.get_orderbook(symbol, depth=self.config["orderbook_depth"])
                current_price = await self.exchange.get_current_price(symbol)
                
                # Получаем волатильность
                try:
                    volatility_data = await self.exchange.get_volatility_data(symbol, "1h")
                    volatility_1h = volatility_data.get("volatility", 0.0)
                except Exception:
                    volatility_1h = 0.0
                
                # Анализируем большие ордера
                large_orders = []
                
                # ASKs (продажи)
                if orderbook.get("asks"):
                    large_asks = self._find_large_orders_in_side_simple(
                        symbol, orderbook["asks"], current_price, "ASK", volatility_1h
                    )
                    large_orders.extend(large_asks)
                
                # BIDs (покупки) 
                if orderbook.get("bids"):
                    large_bids = self._find_large_orders_in_side_simple(
                        symbol, orderbook["bids"], current_price, "BID", volatility_1h
                    )
                    large_orders.extend(large_bids)
                
                # Добавляем найденные ордера
                for order in large_orders:
                    self.add_found_order(order)
                
                self.scanned_symbols += 1
                
                
            except Exception as e:
                self.logger.error(f"Worker {worker_id} error scanning {symbol}: {str(e)}")
                continue
        
        self.logger.debug(f"Worker {worker_id} completed")
    
    def _generate_order_hash(self, symbol: str, price: float, qty: float, side: str) -> str:
        """Генерация уникального хэша для ордера"""
        hash_string = f"{symbol}{price}{qty}{side}{datetime.now().isoformat()}"
        hash_value = hashlib.md5(hash_string.encode()).hexdigest()[:12]
        return f"{symbol[:6]}-{hash_value}"
