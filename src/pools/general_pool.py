"""
Общий пул - сканирует монеты не попавшие в другие стадии
По спецификации: 1 воркер беспрерывно сканирует оставшиеся монеты
"""

import asyncio
from datetime import datetime, timezone
from typing import List, Set, Optional, Dict

from src.workers.base_worker import BaseWorker
from src.exchanges.base_exchange import BaseExchange
from config.main_config import POOLS_CONFIG, PRIMARY_SCAN_CONFIG
from src.utils.logger import get_component_logger

logger = get_component_logger("general_pool")


class GeneralPoolWorker(BaseWorker):
    """Воркер общего пула - сканирует оставшиеся монеты"""
    
    def __init__(self, worker_id: int, config: dict, exchange: BaseExchange, general_pool):
        super().__init__(worker_id, config)
        self.exchange = exchange
        self.general_pool = general_pool
        self.scan_interval = config.get("scan_interval", 2)
        
    async def start(self):
        """Запуск воркера"""
        self.is_running = True
        self.logger.info(f"General pool worker {self.worker_id} started")
        
        # Основной цикл сканирования
        while self.is_running:
            try:
                # Получаем список символов для сканирования
                symbols_to_scan = await self.general_pool.get_symbols_for_scanning()
                
                if symbols_to_scan:
                    self.logger.debug(f"Scanning {len(symbols_to_scan)} symbols")
                    
                    # Сканируем каждый символ
                    for symbol in symbols_to_scan:
                        if not self.is_running:
                            break
                        
                        scan_result = await self.scan_symbol(symbol)
                        if scan_result:
                            await self.process_scan_results([scan_result])
                        
                        # Небольшая задержка между символами
                        await asyncio.sleep(0.1)
                
                else:
                    self.logger.debug("No symbols to scan in general pool")
                
                # Задержка между циклами сканирования
                await asyncio.sleep(self.scan_interval)
                
            except Exception as e:
                self.logger.error(f"Error in general pool worker {self.worker_id}: {str(e)}")
                await asyncio.sleep(5)  # Задержка при ошибке
    
    async def scan_symbol(self, symbol: str) -> Optional[Dict]:
        """Сканирование символа на наличие больших ордеров"""
        try:
            # Получаем стакан и текущую цену
            orderbook = await self.exchange.get_orderbook(symbol, depth=20)
            current_price = await self.exchange.get_current_price(symbol)
            
            # Ищем большие ордера
            large_orders = []
            
            # Анализируем ASKs
            if orderbook.get("asks"):
                large_asks = self._find_large_orders_in_side(
                    symbol, orderbook["asks"], current_price, "ASK"
                )
                large_orders.extend(large_asks)
            
            # Анализируем BIDs
            if orderbook.get("bids"):
                large_bids = self._find_large_orders_in_side(
                    symbol, orderbook["bids"], current_price, "BID"
                )
                large_orders.extend(large_bids)
            
            if large_orders:
                return {
                    "symbol": symbol,
                    "current_price": current_price,
                    "large_orders": large_orders,
                    "scan_time": datetime.now(timezone.utc).isoformat()
                }
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error scanning symbol {symbol}: {str(e)}")
            return None
    
    def _find_large_orders_in_side(self, symbol: str, orders: List, current_price: float, side_type: str) -> List[Dict]:
        """Поиск больших ордеров в одной стороне стакана"""
        if len(orders) < 10:
            return []
        
        # Берем топ-10 ордеров для расчета среднего
        top_10 = orders[:10]
        total_volume = sum(float(price) * float(qty) for price, qty in top_10)
        average_volume = total_volume / 10
        
        # Порог большого ордера (средний объем * коэффициент)
        large_threshold = average_volume * PRIMARY_SCAN_CONFIG["large_order_multiplier"]
        
        large_orders = []
        
        for price, qty in orders:
            price_float = float(price)
            qty_float = float(qty)
            usd_value = price_float * qty_float
            
            if usd_value >= large_threshold:
                distance_percent = abs(price_float - current_price) / current_price * 100
                
                large_order = {
                    "symbol": symbol,
                    "price": price_float,
                    "quantity": qty_float,
                    "type": side_type,
                    "usd_value": usd_value,
                    "distance_percent": distance_percent,
                    "size_vs_average": usd_value / average_volume,
                    "average_order_size": average_volume
                }
                
                large_orders.append(large_order)
        
        return large_orders
    
    async def process_scan_results(self, results: List[Dict]):
        """Обработка результатов сканирования"""
        for result in results:
            if result and result.get("large_orders"):
                # Передаем найденные ордера в пул наблюдателя
                await self.general_pool.handle_large_orders_found(result)


class GeneralPool:
    """
    Общий пул - сканирует монеты не попавшие в другие стадии
    По спецификации: 1 воркер беспрерывно сканирует
    """
    
    def __init__(self, exchange: BaseExchange):
        self.exchange = exchange
        self.config = POOLS_CONFIG["general_pool"]
        self.logger = logger
        
        # Список всех доступных символов
        self.all_symbols: List[str] = []
        
        # Символы, которые сканируются другими пулами (исключаем из общего)
        self.excluded_symbols: Set[str] = set()
        
        # Воркер общего пула
        self.worker: Optional[GeneralPoolWorker] = None
        
        # Ссылка на пул наблюдателя (для передачи найденных ордеров)
        self.observer_pool = None
        
        self.is_running = False
        self.symbols_scanned_count = 0
        self.large_orders_found = 0
    
    async def start(self):
        """Запуск общего пула"""
        if self.is_running:
            return
        
        self.is_running = True
        
        try:
            # Инициализация списка всех символов
            await self._initialize_symbol_list()
            
            # Создание единственного воркера (по спецификации)
            self.worker = GeneralPoolWorker(
                worker_id=0,
                config=self.config,
                exchange=self.exchange,
                general_pool=self
            )
            
            # Запуск воркера
            asyncio.create_task(self.worker.start())
            
            self.logger.info(f"General pool started - symbols: {len(self.all_symbols)}, excluded: {len(self.excluded_symbols)}")
            
        except Exception as e:
            self.logger.error(f"Error starting general pool: {str(e)}")
            self.is_running = False
            raise
    
    async def stop(self):
        """Остановка общего пула"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        if self.worker:
            await self.worker.stop()
        
        self.logger.info(f"General pool stopped - scanned: {self.symbols_scanned_count}, found: {self.large_orders_found}")
    
    async def _initialize_symbol_list(self):
        """Инициализация списка всех доступных символов"""
        try:
            # Получаем все фьючерсные пары
            all_pairs = await self.exchange.get_futures_pairs()
            
            # Получаем топ по объему для приоритизации
            top_symbols = await self.exchange.get_top_volume_symbols(500)  # Берем больше чем топ-250
            
            # Создаем список с приоритизацией (сначала топ символы)
            prioritized_symbols = []
            
            # Добавляем топ символы
            for symbol in top_symbols:
                if symbol in all_pairs:
                    prioritized_symbols.append(symbol)
            
            # Добавляем остальные символы
            for symbol in all_pairs:
                if symbol not in prioritized_symbols:
                    prioritized_symbols.append(symbol)
            
            self.all_symbols = prioritized_symbols
            self.logger.info(f"Initialized symbol list with {len(self.all_symbols)} symbols")
            
        except Exception as e:
            self.logger.error(f"Error initializing symbol list: {str(e)}")
            raise
    
    def add_excluded_symbol(self, symbol: str):
        """Добавить символ в список исключений (используется другими пулами)"""
        self.excluded_symbols.add(symbol)
        self.logger.debug(f"Symbol {symbol} excluded from general pool")
    
    def remove_excluded_symbol(self, symbol: str):
        """Убрать символ из списка исключений (возврат в общий пул)"""
        self.excluded_symbols.discard(symbol)
        self.logger.debug(f"Symbol {symbol} returned to general pool")
    
    async def get_symbols_for_scanning(self) -> List[str]:
        """Получить список символов для сканирования (исключая занятые другими пулами)"""
        # Фильтруем символы, исключая те что обрабатываются другими пулами
        available_symbols = [s for s in self.all_symbols if s not in self.excluded_symbols]
        
        # Возвращаем ограниченное количество для одного цикла сканирования
        # Чтобы не перегружать систему
        batch_size = 50  # Настраиваемый параметр
        return available_symbols[:batch_size]
    
    async def handle_large_orders_found(self, scan_result: Dict):
        """Обработка найденных больших ордеров"""
        try:
            symbol = scan_result["symbol"]
            large_orders = scan_result["large_orders"]
            
            self.logger.info(f"Found {len(large_orders)} large orders in {symbol}")
            self.large_orders_found += len(large_orders)
            
            # Передаем каждый найденный ордер в пул наблюдателя
            if self.observer_pool:
                for order_data in large_orders:
                    # Дополняем данные для пула наблюдателя
                    enhanced_order = {
                        "symbol": order_data["symbol"],
                        "price": order_data["price"],
                        "quantity": order_data["quantity"],
                        "type": order_data["type"],
                        "usd_value": order_data["usd_value"],
                        "distance_percent": order_data["distance_percent"],
                        "size_vs_average": order_data["size_vs_average"],
                        "average_order_size": order_data["average_order_size"],
                        "volatility_1h": 0.0,  # Будет рассчитано в observer pool
                        "is_round_level": self._is_near_round_level(order_data["price"])
                    }
                    
                    self.observer_pool.add_order_from_primary_scan(enhanced_order)
                
                # Исключаем символ из общего пула (теперь его отслеживает observer pool)
                self.add_excluded_symbol(symbol)
            
        except Exception as e:
            self.logger.error(f"Error handling large orders: {str(e)}")
    
    def _is_near_round_level(self, price: float, threshold: float = 0.001) -> bool:
        """Проверка близости к психологическому уровню"""
        round_numbers = [0.1, 0.5, 1.0, 5.0, 10.0, 50.0, 100.0, 500.0, 1000.0]
        
        for base in round_numbers:
            for multiplier in [0.001, 0.01, 0.1, 1, 10, 100, 1000]:
                level = base * multiplier
                if level > 0 and abs(price - level) / level <= threshold:
                    return True
        
        return False
    
    def get_stats(self) -> Dict:
        """Статистика общего пула"""
        total_symbols = len(self.all_symbols)
        excluded_count = len(self.excluded_symbols)
        available_count = total_symbols - excluded_count
        
        return {
            "is_running": self.is_running,
            "total_symbols": total_symbols,
            "excluded_symbols": excluded_count,
            "available_symbols": available_count,
            "symbols_scanned": self.symbols_scanned_count,
            "large_orders_found": self.large_orders_found,
            "worker_running": self.worker.is_running if self.worker else False
        }
