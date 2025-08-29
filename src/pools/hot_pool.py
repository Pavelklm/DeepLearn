"""
Горячий пул - финальная стадия отслеживания ордеров с полной аналитикой
"""

import asyncio
import json
from datetime import datetime, timezone
from typing import Dict, List, Set, Optional
from dataclasses import dataclass, asdict
from pathlib import Path

from src.workers.base_worker import BaseWorker
from src.workers.adaptive_workers import AdaptiveWorkerManager
from src.exchanges.base_exchange import BaseExchange
from src.analytics.weight_calculator import WeightCalculator
from src.analytics.adaptive_categories import AdaptiveCategorizer
from config.main_config import POOLS_CONFIG, FILE_CONFIG, WEIGHT_CATEGORIES
from src.utils.logger import get_component_logger

logger = get_component_logger("hot_pool")


@dataclass
class HotOrder:
    """Структура ордера в горячем пуле с полной аналитикой"""
    # Базовая информация
    order_hash: str
    symbol: str
    exchange: str
    current_price: float
    order_price: float
    quantity: float
    side: str  # ASK или BID
    usd_value: float
    
    # Временные данные
    first_seen: datetime
    last_seen: datetime
    lifetime_seconds: float
    scan_count: int
    
    # Рыночный контекст
    symbol_volatility_1h: float = 0.0
    symbol_volatility_24h: float = 0.0
    market_volatility: float = 0.0
    distance_percent: float = 0.0
    size_vs_average: float = 1.0
    
    # Весовые данные
    time_factors: Dict = None
    weights: Dict = None
    categories: Dict = None
    
    # Аналитика
    is_persistent: bool = True
    is_round_level: bool = False
    growth_trend: str = "stable"  # increasing, decreasing, stable
    stability_score: float = 0.5
    
    def __post_init__(self):
        if self.time_factors is None:
            self.time_factors = {}
        if self.weights is None:
            self.weights = {}
        if self.categories is None:
            self.categories = {}


class HotPoolWorker(BaseWorker):
    """Воркер для горячего пула с максимальной аналитикой"""
    
    def __init__(self, worker_id: int, config: dict, exchange: BaseExchange, hot_pool):
        super().__init__(worker_id, config)
        self.exchange = exchange
        self.hot_pool = hot_pool
        self.weight_calculator = WeightCalculator()
        self.min_scan_interval = config.get("min_scan_interval", 0.5)
        
    async def scan_symbol(self, symbol: str) -> Optional[Dict]:
        """Детальное сканирование символа в горячем пуле"""
        try:
            # Получаем все горячие ордера для символа
            hot_orders = self.hot_pool.get_symbol_orders(symbol)
            if not hot_orders:
                return None
            
            # Получаем актуальные данные рынка
            orderbook = await self.exchange.get_orderbook(symbol, depth=20)
            current_price = await self.exchange.get_current_price(symbol)
            
            # Получаем расширенные данные о волатильности
            try:
                vol_1h = await self.exchange.get_volatility_data(symbol, "1h")
                vol_24h = await self.exchange.get_volatility_data(symbol, "24h")
                symbol_vol_1h = vol_1h.get("volatility", 0.0)
                symbol_vol_24h = vol_24h.get("volatility", 0.0)
            except Exception:
                symbol_vol_1h = symbol_vol_24h = 0.0
            
            # Анализируем каждый горячий ордер
            updates = []
            for hot_order in hot_orders:
                update = await self._analyze_hot_order(
                    hot_order, orderbook, current_price, 
                    symbol_vol_1h, symbol_vol_24h
                )
                if update:
                    updates.append(update)
            
            return {
                "symbol": symbol,
                "current_price": current_price,
                "market_context": {
                    "symbol_volatility_1h": symbol_vol_1h,
                    "symbol_volatility_24h": symbol_vol_24h,
                    "market_temperature": self._calculate_market_temperature(symbol_vol_1h)
                },
                "updates": updates,
                "scan_time": datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            self.logger.error(f"Error scanning symbol in hot pool {symbol}: {str(e)}")
            return None
    
    async def _analyze_hot_order(self, hot_order: HotOrder, orderbook: dict, 
                               current_price: float, vol_1h: float, vol_24h: float) -> Optional[dict]:
        """Детальный анализ горячего ордера"""
        try:
            # Ищем ордер в стакане
            side_orders = orderbook.get("asks" if hot_order.side == "ASK" else "bids", [])
            
            found_order = None
            for price_str, qty_str in side_orders:
                price = float(price_str)
                qty = float(qty_str)
                
                if abs(price - hot_order.order_price) < 1e-8:
                    found_order = {"price": price, "quantity": qty}
                    break
            
            now = datetime.now(timezone.utc)
            
            if not found_order:
                # Ордер исчез - удаляем из горячего пула
                return {
                    "type": "order_disappeared",
                    "order_hash": hot_order.order_hash,
                    "lifetime_seconds": (now - hot_order.first_seen).total_seconds()
                }
            
            # Обновляем базовые параметры
            new_quantity = found_order["quantity"]
            quantity_change = (new_quantity - hot_order.quantity) / hot_order.quantity if hot_order.quantity > 0 else 0
            lifetime_seconds = (now - hot_order.first_seen).total_seconds()
            
            # Рассчитываем рыночный контекст
            market_context = {
                "symbol_volatility_1h": vol_1h,
                "symbol_volatility_24h": vol_24h,
                "market_volatility": vol_1h,  # Упрощенно
                "market_temperature": self._calculate_market_temperature(vol_1h)
            }
            
            # Готовим данные ордера для расчета весов
            order_data = {
                "order_hash": hot_order.order_hash,
                "symbol": hot_order.symbol,
                "price": hot_order.order_price,
                "usd_value": hot_order.usd_value,
                "first_seen": hot_order.first_seen.isoformat(),
                "scan_count": hot_order.scan_count + 1,
                "size_vs_average": hot_order.size_vs_average
            }
            
            # Рассчитываем веса и категории
            weight_data = self.weight_calculator.calculate_order_weight(order_data, market_context)
            
            # Определяем тренд роста
            if quantity_change > 0.1:
                growth_trend = "increasing"
            elif quantity_change < -0.1:
                growth_trend = "decreasing"
            else:
                growth_trend = "stable"
            
            # Рассчитываем стабильность (чем дольше живет - тем стабильнее)
            stability_score = min(1.0, lifetime_seconds / 3600)  # Нормализуем к часу
            
            return {
                "type": "order_updated",
                "order_hash": hot_order.order_hash,
                "updates": {
                    "current_price": current_price,
                    "quantity": new_quantity,
                    "usd_value": current_price * new_quantity,
                    "last_seen": now,
                    "lifetime_seconds": lifetime_seconds,
                    "scan_count": hot_order.scan_count + 1,
                    "symbol_volatility_1h": vol_1h,
                    "symbol_volatility_24h": vol_24h,
                    "distance_percent": abs(hot_order.order_price - current_price) / current_price * 100,
                    "growth_trend": growth_trend,
                    "stability_score": stability_score,
                    **weight_data
                },
                "significant_change": self._is_significant_change(hot_order, weight_data, quantity_change)
            }
            
        except Exception as e:
            self.logger.error(f"Error analyzing hot order {hot_order.order_hash}: {str(e)}")
            return None
    
    def _calculate_market_temperature(self, volatility: float) -> float:
        """Рассчитать температуру рынка"""
        if volatility > 0.1:
            return 2.0  # Горячий
        elif volatility > 0.05:
            return 1.5  # Теплый
        elif volatility < 0.01:
            return 0.5  # Холодный
        else:
            return 1.0  # Нормальный
    
    def _is_significant_change(self, hot_order: HotOrder, weight_data: dict, quantity_change: float) -> bool:
        """Определить значимость изменений"""
        config = self.config
        
        # Проверяем изменение веса
        new_weight = weight_data.get("weights", {}).get("recommended", 0)
        old_weight = hot_order.weights.get("recommended", 0) if hot_order.weights else 0
        weight_change = abs(new_weight - old_weight)
        
        if weight_change > config.get("weight_change_threshold", 0.05):
            return True
        
        # Проверяем изменение USD стоимости
        if abs(quantity_change) > config.get("usd_change_threshold", 0.05):
            return True
        
        # Проверяем изменение категории
        new_category = weight_data.get("categories", {}).get("recommended", "basic")
        old_category = hot_order.categories.get("recommended", "basic") if hot_order.categories else "basic"
        
        if new_category != old_category:
            return True
        
        return False
    
    async def process_scan_results(self, results: List[Dict]):
        """Обработка результатов сканирования"""
        for result in results:
            if result and "updates" in result:
                await self.hot_pool.handle_updates(result)


class HotPoolWorkerWrapper(BaseWorker):
    """Обертка для HotPoolWorker"""
    
    def __init__(self, worker_id: int, config: dict):
        exchange = config.pop("exchange")
        hot_pool = config.pop("hot_pool")
        self.worker = HotPoolWorker(worker_id, config, exchange, hot_pool)
    
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
    
    @property
    def is_running(self):
        return self.worker.is_running
    
    @property
    def worker_id(self):
        return self.worker.worker_id
    
    @property
    def assigned_symbols(self):
        return self.worker.assigned_symbols


class HotPool:
    """Горячий пул для финального отслеживания ордеров"""
    
    def __init__(self, exchange: BaseExchange):
        self.exchange = exchange
        self.config = POOLS_CONFIG["hot_pool"]
        self.logger = logger
        
        # Хранилище горячих ордеров
        self.hot_orders: Dict[str, HotOrder] = {}
        self.symbol_orders: Dict[str, Set[str]] = {}
        
        # Менеджер воркеров
        self.worker_manager = AdaptiveWorkerManager(
            worker_class=HotPoolWorkerWrapper,
            config={
                **self.config,
                "exchange": exchange,
                "hot_pool": self
            }
        )
        
        # Компоненты аналитики
        self.weight_calculator = WeightCalculator()
        self.categorizer = AdaptiveCategorizer()
        
        # WebSocket сервер для трансляции данных
        self.websocket_server = None
        
        # Файловое хранилище
        self.output_file = Path(FILE_CONFIG["hot_orders_file"])
        self.output_file.parent.mkdir(exist_ok=True)
        
        # Задача сохранения
        self.save_task = None
        self.last_save_time = datetime.now()
        
        self.is_running = False
    
    async def start(self):
        """Запуск горячего пула"""
        if self.is_running:
            return
        
        self.is_running = True
        await self.worker_manager.start()
        
        # Запускаем задачу периодического сохранения
        self.save_task = asyncio.create_task(self._save_loop())
        
        self.logger.info("Hot pool started")
    
    async def stop(self):
        """Остановка горячего пула"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        await self.worker_manager.stop()
        
        if self.save_task:
            self.save_task.cancel()
            try:
                await self.save_task
            except asyncio.CancelledError:
                pass
        
        # Финальное сохранение
        await self._save_to_file()
        
        self.logger.info(f"Hot pool stopped with {len(self.hot_orders)} total orders")
    
    async def add_order_from_observer(self, tracked_order, update_data: dict):
        """Добавить ордер из пула наблюдателя"""
        try:
            # Создаем горячий ордер на основе отслеживаемого
            hot_order = HotOrder(
                order_hash=tracked_order.order_hash,
                symbol=tracked_order.symbol,
                exchange=self.exchange.name,
                current_price=tracked_order.price,  # Будет обновлена при первом сканировании
                order_price=tracked_order.price,
                quantity=tracked_order.quantity,
                side=tracked_order.side,
                usd_value=tracked_order.usd_value,
                first_seen=tracked_order.first_seen,
                last_seen=tracked_order.last_seen,
                lifetime_seconds=update_data.get("lifetime_seconds", 0),
                scan_count=tracked_order.scan_count
            )
            
            # Добавляем в хранилище
            self.hot_orders[hot_order.order_hash] = hot_order
            
            if hot_order.symbol not in self.symbol_orders:
                self.symbol_orders[hot_order.symbol] = set()
            self.symbol_orders[hot_order.symbol].add(hot_order.order_hash)
            
            # Обновляем воркеров
            self._update_worker_assignments()
            
            self.logger.info(f"Added order to hot pool: {hot_order.order_hash} ({hot_order.symbol}) lifetime={hot_order.lifetime_seconds}s")
            
        except Exception as e:
            self.logger.error(f"Error adding order to hot pool: {tracked_order} - {str(e)}")
    
    async def handle_updates(self, scan_result: dict):
        """Обработка обновлений от воркеров"""
        try:
            for update in scan_result.get("updates", []):
                update_type = update.get("type")
                order_hash = update.get("order_hash")
                
                if not order_hash or order_hash not in self.hot_orders:
                    continue
                
                if update_type == "order_updated":
                    await self._update_hot_order(order_hash, update.get("updates", {}))
                    
                    # Если изменения значимые - сохраняем немедленно
                    if update.get("significant_change", False):
                        await self._save_to_file()
                        
                        # Отправляем обновление через WebSocket
                        await self._broadcast_hot_pool_update()
                        
                        # Отправляем алерт для diamond ордеров
                        await self._check_alert_conditions(order_hash, update.get("updates", {}))
                        
                elif update_type == "order_disappeared":
                    self._remove_hot_order(order_hash)
                    await self._save_to_file()
                    
                    # Отправляем обновление через WebSocket
                    await self._broadcast_hot_pool_update()
                    
        except Exception as e:
            self.logger.error(f"Error handling updates: {str(e)}")
    
    async def _update_hot_order(self, order_hash: str, updates: dict):
        """Обновление горячего ордера"""
        try:
            hot_order = self.hot_orders[order_hash]
            
            # Обновляем поля
            for field, value in updates.items():
                if hasattr(hot_order, field):
                    setattr(hot_order, field, value)
            
            self.logger.debug(f"Updated hot order {order_hash}: weight={updates.get('weights', {}).get('recommended', 0):.3f} category={updates.get('categories', {}).get('recommended', 'basic')}")
            
        except Exception as e:
            self.logger.error(f"Error updating hot order {order_hash}: {str(e)}")
    
    def _remove_hot_order(self, order_hash: str):
        """Удаление горячего ордера"""
        try:
            if order_hash not in self.hot_orders:
                return
            
            hot_order = self.hot_orders[order_hash]
            symbol = hot_order.symbol
            
            # Удаляем из основного хранилища
            del self.hot_orders[order_hash]
            
            # Удаляем из индекса символов
            if symbol in self.symbol_orders:
                self.symbol_orders[symbol].discard(order_hash)
                if not self.symbol_orders[symbol]:
                    del self.symbol_orders[symbol]
            
            self.logger.debug(f"Removed hot order {order_hash} from {symbol}")
            
            # Обновляем воркеров
            self._update_worker_assignments()
            
        except Exception as e:
            self.logger.error(f"Error removing hot order {order_hash}: {str(e)}")
    
    def _update_worker_assignments(self):
        """Обновление назначений воркеров"""
        active_symbols = list(self.symbol_orders.keys())
        
        # Адаптивное масштабирование
        asyncio.create_task(self.worker_manager.scale_based_on_load(len(active_symbols)))
        
        # Распределение работы
        self.worker_manager.distribute_work(active_symbols)
    
    async def _save_loop(self):
        """Цикл периодического сохранения"""
        save_interval = FILE_CONFIG.get("save_interval", 1)
        
        while self.is_running:
            try:
                await asyncio.sleep(save_interval)
                
                # Сохраняем только если есть изменения
                if self.hot_orders and self._should_save():
                    await self._save_to_file()
                    
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in save loop: {str(e)}")
    
    def _should_save(self) -> bool:
        """Определить нужно ли сохранять"""
        return (datetime.now() - self.last_save_time).total_seconds() >= 1
    
    async def _save_to_file(self):
        """Сохранение в файл в реальном времени"""
        try:
            if not self.hot_orders:
                return
            
            # Готовим данные для сохранения
            export_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_orders": len(self.hot_orders),
                "active_symbols": len(self.symbol_orders),
                "exchange": self.exchange.name,
                "orders": []
            }
            
            # Сортируем по весу (рекомендуемому)
            sorted_orders = sorted(
                self.hot_orders.values(),
                key=lambda x: x.weights.get("recommended", 0) if x.weights else 0,
                reverse=True
            )
            
            for hot_order in sorted_orders:
                order_dict = asdict(hot_order)
                # Конвертируем datetime в строки
                order_dict["first_seen"] = hot_order.first_seen.isoformat()
                order_dict["last_seen"] = hot_order.last_seen.isoformat()
                export_data["orders"].append(order_dict)
            
            # Сохраняем атомарно
            temp_file = self.output_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False)
            
            temp_file.replace(self.output_file)
            self.last_save_time = datetime.now()
            
            self.logger.debug(f"Saved hot pool data: {len(self.hot_orders)} orders, file size: {self.output_file.stat().st_size} bytes")
            
        except Exception as e:
            self.logger.error(f"Error saving to file: {str(e)}")
    
    async def _broadcast_hot_pool_update(self):
        """Отправка обновлений горячего пула через WebSocket"""
        if not self.websocket_server or not self.websocket_server.is_running:
            return
        
        try:
            # Подготавливаем данные для отправки
            hot_pool_data = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "total_orders": len(self.hot_orders),
                "active_symbols": len(self.symbol_orders),
                "exchange": self.exchange.name,
                "orders": []
            }
            
            # Сортируем по весу (только топ-20 для WebSocket)
            sorted_orders = sorted(
                self.hot_orders.values(),
                key=lambda x: x.weights.get("recommended", 0) if x.weights else 0,
                reverse=True
            )[:20]  # Ограничиваем для производительности
            
            for hot_order in sorted_orders:
                order_data = {
                    "order_hash": hot_order.order_hash,
                    "symbol": hot_order.symbol,
                    "exchange": hot_order.exchange,
                    "current_price": hot_order.current_price,
                    "order_price": hot_order.order_price,
                    "quantity": hot_order.quantity,
                    "side": hot_order.side,
                    "usd_value": hot_order.usd_value,
                    "lifetime_seconds": hot_order.lifetime_seconds,
                    "scan_count": hot_order.scan_count,
                    "distance_percent": hot_order.distance_percent,
                    "growth_trend": hot_order.growth_trend,
                    "stability_score": hot_order.stability_score,
                    "weights": hot_order.weights,
                    "categories": hot_order.categories,
                    "first_seen": hot_order.first_seen.isoformat(),
                    "last_seen": hot_order.last_seen.isoformat()
                }
                hot_pool_data["orders"].append(order_data)
            
            # Отправляем через WebSocket
            await self.websocket_server.send_hot_pool_data(hot_pool_data)
            
        except Exception as e:
            self.logger.error(f"Error broadcasting hot pool update: {str(e)}")
    
    async def _check_alert_conditions(self, order_hash: str, updates: dict):
        """Проверка условий для алертов"""
        try:
            # Получаем горячий ордер
            if order_hash not in self.hot_orders:
                return
            
            hot_order = self.hot_orders[order_hash]
            
            # Проверяем diamond ордер
            category = updates.get("categories", {}).get("recommended", "basic")
            if category == "diamond":
                # Импортируем локально чтобы избежать циклических импортов
                from src.alerts.alert_manager import alert_diamond_order
                
                await alert_diamond_order(
                    symbol=hot_order.symbol,
                    usd_value=hot_order.usd_value,
                    weight=updates.get("weights", {}).get("recommended", 0),
                    exchange=hot_order.exchange,
                    side=hot_order.side,
                    price=hot_order.order_price,
                    lifetime_seconds=hot_order.lifetime_seconds
                )
            
            # Проверяем очень большие ордера
            if hot_order.usd_value > 100000:
                from src.alerts.alert_manager import get_alert_manager
                
                manager = get_alert_manager()
                context = {
                    'usd_value': hot_order.usd_value,
                    'symbol': hot_order.symbol,
                    'exchange': hot_order.exchange,
                    'side': hot_order.side,
                    'price': hot_order.order_price
                }
                await manager.check_conditions(context)
                
        except Exception as e:
            self.logger.error(f"Error checking alert conditions for {order_hash}: {str(e)}")
    
    def get_symbol_orders(self, symbol: str) -> List[HotOrder]:
        """Получить горячие ордера для символа"""
        if symbol not in self.symbol_orders:
            return []
        
        order_hashes = self.symbol_orders[symbol]
        return [self.hot_orders[hash_] for hash_ in order_hashes if hash_ in self.hot_orders]
    
    def get_stats(self) -> dict:
        """Статистика горячего пула"""
        if not self.hot_orders:
            return {
                "is_running": self.is_running,
                "total_orders": 0,
                "active_symbols": 0,
                "categories": {"basic": 0, "gold": 0, "diamond": 0},
                "worker_stats": self.worker_manager.get_all_stats()
            }
        
        # Категоризация по весам
        categories = {"basic": 0, "gold": 0, "diamond": 0}
        for order in self.hot_orders.values():
            if order.categories:
                category = order.categories.get("recommended", "basic")
                categories[category] = categories.get(category, 0) + 1
        
        return {
            "is_running": self.is_running,
            "total_orders": len(self.hot_orders),
            "active_symbols": len(self.symbol_orders),
            "categories": categories,
            "avg_lifetime": sum(o.lifetime_seconds for o in self.hot_orders.values()) / len(self.hot_orders),
            "avg_weight": sum(o.weights.get("recommended", 0) for o in self.hot_orders.values() if o.weights) / len(self.hot_orders),
            "worker_stats": self.worker_manager.get_all_stats(),
            "last_save_time": self.last_save_time.isoformat()
        }
