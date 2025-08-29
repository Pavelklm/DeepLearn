"""
Пул наблюдателя - отслеживание ордеров до перехода в горячий пул
"""

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Dict, List, Set, Optional
from dataclasses import dataclass

from src.workers.base_worker import BaseWorker
from src.workers.adaptive_workers import AdaptiveWorkerManager
from src.exchanges.base_exchange import BaseExchange
from config.main_config import POOLS_CONFIG
from src.utils.logger import get_component_logger

logger = get_component_logger("observer_pool")


@dataclass
class TrackedOrder:
    """Структура отслеживаемого ордера"""
    order_hash: str
    symbol: str
    price: float
    quantity: float
    side: str
    usd_value: float
    first_seen: datetime
    last_seen: datetime
    scan_count: int
    is_persistent: bool = False
    original_quantity: float = None
    
    def __post_init__(self):
        if self.original_quantity is None:
            self.original_quantity = self.quantity


class ObserverWorkerWrapper(BaseWorker):
    """Обертка для ObserverWorker для совместимости с AdaptiveWorkerManager"""
    
    def __init__(self, worker_id: int, config: dict):
        # Извлекаем нужные параметры из конфига
        exchange = config.pop("exchange")
        observer_pool = config.pop("observer_pool")
        
        # Создаем реальный ObserverWorker
        self.worker = ObserverWorker(worker_id, config, exchange, observer_pool)
    
    async def scan_symbol(self, symbol: str):
        return await self.worker.scan_symbol(symbol)
    
    async def process_scan_results(self, results):
        return await self.worker.process_scan_results(results)
    
    async def start(self):
        return await self.worker.start()
    
    async def stop(self):
        return await self.worker.stop()
    
    def assign_symbols(self, symbols):
        return self.worker.assign_symbols(symbols)
    
    def get_stats(self):
        return self.worker.get_stats()
    
    # Проксируем все свойства
    @property
    def is_running(self):
        return self.worker.is_running
    
    @property
    def worker_id(self):
        return self.worker.worker_id
    
    @property
    def assigned_symbols(self):
        return self.worker.assigned_symbols


class ObserverWorker(BaseWorker):
    """Воркер для наблюдения за ордерами в пуле наблюдателя"""
    
    def __init__(self, worker_id: int, config: dict, exchange: BaseExchange, observer_pool):
        super().__init__(worker_id, config)
        self.exchange = exchange
        self.observer_pool = observer_pool
        self.survival_threshold = config.get("survival_threshold", 0.7)
    
    async def scan_symbol(self, symbol: str) -> Optional[Dict]:
        """Сканирование символа в пуле наблюдателя"""
        try:
            # Получаем текущий стакан
            orderbook = await self.exchange.get_orderbook(symbol, depth=20)
            current_price = await self.exchange.get_current_price(symbol)
            
            # Проверяем существующие отслеживаемые ордера для этого символа
            tracked_orders = self.observer_pool.get_symbol_orders(symbol)
            
            if not tracked_orders:
                return None
            
            # Анализируем каждый отслеживаемый ордер
            results = []
            
            for tracked_order in tracked_orders:
                order_update = self._analyze_tracked_order(
                    tracked_order, orderbook, current_price
                )
                if order_update:
                    results.append(order_update)
            
            return {
                "symbol": symbol,
                "current_price": current_price,
                "updates": results,
                "scan_time": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Error scanning symbol in observer {symbol}: {str(e)}")
            return None
    
    def _analyze_tracked_order(self, tracked_order: TrackedOrder, 
                              orderbook: dict, current_price: float) -> Optional[dict]:
        """Анализ конкретного отслеживаемого ордера"""
        try:
            # Ищем ордер в текущем стакане
            side_orders = orderbook.get("asks" if tracked_order.side == "ASK" else "bids", [])
            
            found_order = None
            for price_str, qty_str in side_orders:
                price = float(price_str)
                qty = float(qty_str)
                
                # Проверяем точное совпадение цены
                if abs(price - tracked_order.price) < 1e-8:
                    found_order = {"price": price, "quantity": qty}
                    break
            
            now = datetime.now(timezone.utc)
            
            if found_order:
                # Ордер найден - обновляем информацию
                new_quantity = found_order["quantity"]
                quantity_change = (new_quantity - tracked_order.original_quantity) / tracked_order.original_quantity
                
                # Проверяем порог выживания
                if quantity_change <= -self.survival_threshold:
                    # Ордер потерял более 30% (или настроенного порога) - считается "мертвым"
                    return {
                        "type": "order_died",
                        "order_hash": tracked_order.order_hash,
                        "reason": "quantity_loss",
                        "quantity_change": quantity_change,
                        "lifetime_seconds": (now - tracked_order.first_seen).total_seconds()
                    }
                
                # Проверяем время жизни для перехода в горячий пул
                lifetime_seconds = (now - tracked_order.first_seen).total_seconds()
                hot_pool_threshold = self.config.get("hot_pool_lifetime_seconds", 60)
                
                if lifetime_seconds >= hot_pool_threshold and not tracked_order.is_persistent:
                    # Ордер живет достаточно долго - переводим в горячий пул
                    return {
                        "type": "move_to_hot_pool",
                        "order_hash": tracked_order.order_hash,
                        "lifetime_seconds": lifetime_seconds,
                        "current_quantity": new_quantity,
                        "quantity_change": quantity_change
                    }
                
                # Обычное обновление ордера
                return {
                    "type": "order_updated",
                    "order_hash": tracked_order.order_hash,
                    "new_quantity": new_quantity,
                    "quantity_change": quantity_change,
                    "scan_count": tracked_order.scan_count + 1
                }
            
            else:
                # Ордер исчез из стакана
                return {
                    "type": "order_disappeared",
                    "order_hash": tracked_order.order_hash,
                    "lifetime_seconds": (now - tracked_order.first_seen).total_seconds(),
                    "last_quantity": tracked_order.quantity
                }
                
        except Exception as e:
            self.logger.error(f"Error analyzing tracked order {tracked_order.order_hash}: {str(e)}")
            return None
    
    async def process_scan_results(self, results: List[Dict]):
        """Обработка результатов сканирования"""
        for result in results:
            if result and "updates" in result:
                for update in result["updates"]:
                    await self.observer_pool.handle_order_update(update)


class ObserverPool:
    """Пул наблюдателя для отслеживания ордеров"""
    
    def __init__(self, exchange: BaseExchange):
        self.exchange = exchange
        self.config = POOLS_CONFIG["observer_pool"]
        self.logger = logger
        
        # Хранилище отслеживаемых ордеров
        self.tracked_orders: Dict[str, TrackedOrder] = {}  # order_hash -> TrackedOrder
        self.symbol_orders: Dict[str, Set[str]] = {}  # symbol -> set of order_hashes
        
        # Менеджер воркеров с передачей параметров
        self.worker_manager = AdaptiveWorkerManager(
            worker_class=ObserverWorkerWrapper, 
            config={
                **self.config,
                "exchange": exchange,
                "observer_pool": self
            }
        )
        
        # Счетчики для статистики
        self.orders_moved_to_hot = 0
        self.orders_died = 0
        self.cleanup_scan_counts: Dict[str, int] = {}  # symbol -> scans_since_empty
        
        self.is_running = False
    
    async def start(self):
        """Запуск пула наблюдателя"""
        if self.is_running:
            return
        
        self.is_running = True
        await self.worker_manager.start()
        
        # Запускаем задачу периодической очистки
        asyncio.create_task(self._cleanup_task())
        
        self.logger.info("Observer pool started")
    
    async def stop(self):
        """Остановка пула наблюдателя"""
        if not self.is_running:
            return
        
        self.is_running = False
        await self.worker_manager.stop()
        
        self.logger.info(f"Observer pool stopped - tracked: {len(self.tracked_orders)}, moved to hot: {self.orders_moved_to_hot}, died: {self.orders_died}")
    
    def add_order_from_primary_scan(self, order_data: dict):
        """Добавить ордер из первичного сканирования"""
        try:
            # Создаем хэш ордера
            order_hash = self._generate_order_hash(order_data)
            
            # Проверяем что ордер еще не отслеживается
            if order_hash in self.tracked_orders:
                return
            
            # Создаем отслеживаемый ордер
            tracked_order = TrackedOrder(
                order_hash=order_hash,
                symbol=order_data["symbol"],
                price=order_data["price"],
                quantity=order_data["quantity"],
                side=order_data["type"],
                usd_value=order_data["usd_value"],
                first_seen=datetime.now(timezone.utc),
                last_seen=datetime.now(timezone.utc),
                scan_count=1
            )
            
            # Добавляем в хранилище
            self.tracked_orders[order_hash] = tracked_order
            
            # Добавляем связь символ -> ордер
            if tracked_order.symbol not in self.symbol_orders:
                self.symbol_orders[tracked_order.symbol] = set()
            self.symbol_orders[tracked_order.symbol].add(order_hash)
            
            # Обновляем работу воркеров
            self._update_worker_assignments()
            
            self.logger.debug(f"Added order to observer pool: {order_hash} ({tracked_order.symbol}) ${tracked_order.usd_value:,.0f}")
            
        except Exception as e:
            self.logger.error(f"Error adding order to observer pool {order_data}: {str(e)}")
    
    async def handle_order_update(self, update: dict):
        """Обработка обновления ордера"""
        try:
            update_type = update.get("type")
            order_hash = update.get("order_hash")
            
            if not order_hash or order_hash not in self.tracked_orders:
                return
            
            tracked_order = self.tracked_orders[order_hash]
            
            if update_type == "order_updated":
                # Обычное обновление
                tracked_order.quantity = update["new_quantity"]
                tracked_order.last_seen = datetime.now(timezone.utc)
                tracked_order.scan_count += 1
                
            elif update_type == "move_to_hot_pool":
                # Перевод в горячий пул
                await self._move_order_to_hot_pool(tracked_order, update)
                
            elif update_type in ["order_died", "order_disappeared"]:
                # Удаление мертвого/исчезнувшего ордера
                self._remove_order(tracked_order, update_type)
                
        except Exception as e:
            self.logger.error(f"Error handling order update {update}: {str(e)}")
    
    async def _move_order_to_hot_pool(self, tracked_order: TrackedOrder, update: dict):
        """Перевод ордера в горячий пул"""
        try:
            # Проверяем наличие горячего пула
            if hasattr(self, 'hot_pool') and self.hot_pool:
                await self.hot_pool.add_order_from_observer(tracked_order, update)
            else:
                # Горячий пул не создан - просто логируем
                self.logger.info(f"Order ready for hot pool (not initialized): {tracked_order.order_hash} ({tracked_order.symbol}) lifetime={update['lifetime_seconds']}s")
            
            self.orders_moved_to_hot += 1
            
            # Удаляем из пула наблюдателя
            self._remove_order(tracked_order, "moved_to_hot_pool")
            
        except Exception as e:
            self.logger.error(f"Error moving order to hot pool {tracked_order.order_hash}: {str(e)}")
    
    def _remove_order(self, tracked_order: TrackedOrder, reason: str):
        """Удаление ордера из пула наблюдателя"""
        try:
            order_hash = tracked_order.order_hash
            symbol = tracked_order.symbol
            
            # Удаляем из основного хранилища
            if order_hash in self.tracked_orders:
                del self.tracked_orders[order_hash]
            
            # Удаляем связь символ -> ордер
            if symbol in self.symbol_orders:
                self.symbol_orders[symbol].discard(order_hash)
                
                # Если у символа не осталось ордеров - начинаем отсчет до удаления
                if not self.symbol_orders[symbol]:
                    self.cleanup_scan_counts[symbol] = 0
            
            if reason in ["order_died", "order_disappeared"]:
                self.orders_died += 1
            
            self.logger.debug(f"Removed order from observer pool: {order_hash} ({symbol}) reason: {reason}")
            
            # Обновляем назначения воркеров
            self._update_worker_assignments()
            
        except Exception as e:
            self.logger.error(f"Error removing order {tracked_order.order_hash}: {str(e)}")
    
    def _update_worker_assignments(self):
        """Обновление назначений символов воркерам"""
        active_symbols = [symbol for symbol, orders in self.symbol_orders.items() if orders]
        
        # Масштабируем воркеров на основе нагрузки
        asyncio.create_task(self.worker_manager.scale_based_on_load(len(active_symbols)))
        
        # Распределяем символы между воркерами
        self.worker_manager.distribute_work(active_symbols)
    
    async def _cleanup_task(self):
        """Периодическая задача очистки пустых символов"""
        cleanup_scans = self.config.get("cleanup_scans", 10)
        
        while self.is_running:
            try:
                symbols_to_remove = []
                
                for symbol, scan_count in self.cleanup_scan_counts.items():
                    self.cleanup_scan_counts[symbol] += 1
                    
                    if self.cleanup_scan_counts[symbol] >= cleanup_scans:
                        symbols_to_remove.append(symbol)
                
                # Удаляем символы которые пустые слишком долго
                for symbol in symbols_to_remove:
                    if symbol in self.symbol_orders:
                        del self.symbol_orders[symbol]
                    del self.cleanup_scan_counts[symbol]
                    
                    self.logger.debug(f"Cleaned up empty symbol: {symbol}")
                
                if symbols_to_remove:
                    self._update_worker_assignments()
                
            except Exception as e:
                self.logger.error(f"Error in cleanup task: {str(e)}")
            
            await asyncio.sleep(self.config.get("scan_interval", 1))
    
    def get_symbol_orders(self, symbol: str) -> List[TrackedOrder]:
        """Получить все отслеживаемые ордера для символа"""
        if symbol not in self.symbol_orders:
            return []
        
        order_hashes = self.symbol_orders[symbol]
        return [self.tracked_orders[hash_] for hash_ in order_hashes if hash_ in self.tracked_orders]
    
    def _generate_order_hash(self, order_data: dict) -> str:
        """Генерация хэша ордера"""
        hash_string = f"{order_data['symbol']}{order_data['price']}{order_data['quantity']}{order_data['type']}"
        return f"{order_data['symbol'][:6]}-{hashlib.md5(hash_string.encode()).hexdigest()[:12]}"
    
    def get_stats(self) -> dict:
        """Получить статистику пула наблюдателя"""
        total_orders = len(self.tracked_orders)
        symbols_count = len([s for s, orders in self.symbol_orders.items() if orders])
        
        # Группировка по символам
        orders_by_symbol = {}
        for symbol, order_hashes in self.symbol_orders.items():
            if order_hashes:
                orders_by_symbol[symbol] = len(order_hashes)
        
        return {
            "is_running": self.is_running,
            "total_orders": total_orders,
            "active_symbols": symbols_count,
            "orders_by_symbol": orders_by_symbol,
            "orders_moved_to_hot": self.orders_moved_to_hot,
            "orders_died": self.orders_died,
            "worker_stats": self.worker_manager.get_all_stats()
        }
