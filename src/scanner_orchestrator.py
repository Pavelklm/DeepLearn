"""
Оркестратор системы - координация компонентов строго по спецификации
"""

import asyncio
from typing import List, Dict, Optional
from datetime import datetime, timezone

from src.exchanges.base_exchange import BaseExchange
from src.exchanges.exchange_factory import get_exchange
from src.pools.primary_scanner import PrimaryScanner
from src.pools.observer_pool import ObserverPool
from src.pools.general_pool import GeneralPool
from src.pools.hot_pool import HotPool
from src.websocket.server import get_websocket_server
from config.main_config import PRIMARY_SCAN_CONFIG
from src.utils.logger import (
    SimpleLogger, log_scan_results, log_exchange_connection,
    log_hot_pool_update, Timer
)

logger = SimpleLogger("orchestrator")


class ScannerOrchestrator:
    """Главный оркестратор системы сканирования - строго по спецификации"""
    
    def __init__(self, exchanges: List[str] = None, testnet: bool = False):
        self.exchanges_names = exchanges or ["binance"]
        self.testnet = testnet
        self.logger = logger
        
        # Компоненты системы (ТОЛЬКО по спецификации)
        self.exchanges: Dict[str, BaseExchange] = {}
        self.primary_scanner = None
        self.general_pool = None
        self.observer_pool = None
        self.hot_pool = None
        self.websocket_server = None
        
        # Состояние системы
        self.is_running = False
        self.primary_scan_completed = False
        
    async def start(self):
        """Запуск полной системы по спецификации"""
        if self.is_running:
            return
        
        try:
            self.logger.start_operation("запуск системы")
            self.is_running = True
            
            # 1. Подключаем биржи
            await self._initialize_exchanges()
            
            # 2. Создаем компоненты системы (ТОЛЬКО по спецификации)
            await self._create_components()
            
            # 3. Запускаем WebSocket сервер (из спецификации)
            if self.websocket_server:
                await self.websocket_server.start()
                self.logger.info("WebSocket сервер запущен")
            
            # 4. Запускаем первичное сканирование (Этап 1)
            await self._run_primary_scan()
            
            # 5. Запускаем постоянные пулы (Этапы 2-3)
            await self._start_continuous_pools()
            
            self.logger.finish_operation("запуск системы", success=True)
            
        except Exception as e:
            self.logger.error(f"Ошибка запуска оркестратора: {e}")
            await self.stop()
            raise
    
    async def _initialize_exchanges(self):
        """Инициализация бирж"""
        for exchange_name in self.exchanges_names:
            try:
                exchange = await get_exchange(exchange_name, self.testnet)
                if exchange:
                    self.exchanges[exchange_name] = exchange
                    
                    # Тестируем подключение
                    pairs = await exchange.get_futures_pairs()
                    log_exchange_connection(exchange_name, True, len(pairs))
                else:
                    log_exchange_connection(exchange_name, False)
                    
            except Exception as e:
                self.logger.error(f"Ошибка инициализации биржи {exchange_name}: {e}")
        
        if not self.exchanges:
            raise Exception("Ни одна биржа не была инициализирована")
    
    async def _create_components(self):
        """Создание компонентов системы строго по спецификации"""
        # Используем первую доступную биржу как основную
        main_exchange = list(self.exchanges.values())[0]
        
        # Создаем компоненты в порядке зависимостей по спецификации:
        
        # 1. Горячий пул (независимый)
        self.hot_pool = HotPool(main_exchange)
        
        # 2. Пул наблюдателя (связь с горячим пулом)
        self.observer_pool = ObserverPool(main_exchange)
        self.observer_pool.hot_pool = self.hot_pool
        
        # 3. Общий пул (связь с пулом наблюдателя)
        self.general_pool = GeneralPool(main_exchange)
        self.general_pool.observer_pool = self.observer_pool
        
        # 4. Первичный сканнер (связь с пулом наблюдателя)
        self.primary_scanner = PrimaryScanner(main_exchange, self.observer_pool)
        
        # 5. WebSocket сервер (для передачи данных)
        self.websocket_server = await get_websocket_server()
        
        # Связываем горячий пул с WebSocket для автоматической трансляции
        if self.websocket_server and self.hot_pool:
            self.hot_pool.websocket_server = self.websocket_server
        
        self.logger.info("Все компоненты созданы согласно спецификации")
    
    async def _run_primary_scan(self):
        """Запуск первичного сканирования (Этап 1 спецификации)"""
        self.logger.start_operation("первичное сканирование")
        
        try:
            with Timer(self.logger, "полное первичное сканирование"):
                scan_results = await self.primary_scanner.run_full_scan()
            
            self.primary_scan_completed = True
            
            # Логируем результаты
            log_scan_results(
                scan_results["total_large_orders"],
                scan_results["total_symbols_scanned"],
                scan_results["duration_seconds"]
            )
            
            return scan_results
            
        except Exception as e:
            self.logger.error(f"Ошибка первичного сканирования: {e}")
            raise
    
    async def _start_continuous_pools(self):
        """Запуск постоянных пулов (Этапы 2-3 спецификации)"""        
        if not self.primary_scan_completed:
            self.logger.warning("Запуск постоянных пулов без завершенного первичного сканирования")
        
        # Запускаем пулы в правильном порядке по спецификации:
        
        # 1. Горячий пул (принимает ордера от observer pool)
        await self.hot_pool.start()
        self.logger.info("Горячий пул запущен")
        
        # 2. Пул наблюдателя (принимает ордера от general pool и primary scanner)
        await self.observer_pool.start()
        self.logger.info("Пул наблюдателя запущен")
        
        # 3. Общий пул (сканирует оставшиеся монеты, отправляет в observer pool)
        await self.general_pool.start()
        self.logger.info("Общий пул запущен")
        
        self.logger.success("Все постоянные пулы запущены")
    
    async def run_test_mode(self, symbols_count: int = 5) -> Dict:
        """Запуск в тестовом режиме"""
        self.logger.start_operation(f"тестовый режим ({symbols_count} символов)")
        
        try:
            # Подключаемся к основной бирже
            main_exchange = await get_exchange(self.exchanges_names[0], self.testnet)
            if not main_exchange:
                raise Exception("Не удалось подключиться к основной бирже")
            
            self.exchanges[self.exchanges_names[0]] = main_exchange
            
            # Создаем компоненты
            await self._create_components()
            
            # Запускаем пул наблюдателя и горячий пул
            await self.observer_pool.start()
            await self.hot_pool.start()
            
            # Получаем топ символы
            top_symbols = await main_exchange.get_top_volume_symbols(250)
            test_symbols = top_symbols[:symbols_count]
            
            # Запускаем тестовое сканирование
            with Timer(self.logger, "тестовое сканирование"):
                scan_results = await self.primary_scanner.run_test_scan(test_symbols)
            
            # Даем время системе поработать
            self.logger.info("Система работает в тестовом режиме...")
            await asyncio.sleep(10)  # 10 секунд наблюдения
            
            # Собираем финальную статистику
            final_stats = {
                "scan_results": scan_results,
                "observer_stats": self.observer_pool.get_stats(),
                "hot_pool_stats": self.hot_pool.get_stats(),
                "test_duration": 10
            }
            
            self.logger.finish_operation("тестовый режим", success=True)
            return final_stats
            
        except Exception as e:
            self.logger.error(f"Ошибка тестового режима: {e}")
            raise
        finally:
            await self.stop()
    
    async def stop(self):
        """Остановка системы (в обратном порядке по спецификации)"""
        if not self.is_running:
            return
        
        self.logger.start_operation("остановка системы")
        self.is_running = False
        
        # Останавливаем компоненты в обратном порядке:
        
        # 1. Общий пул (последний запущенный)
        if self.general_pool:
            await self.general_pool.stop()
            self.logger.debug("Общий пул остановлен")
        
        # 2. Пул наблюдателя  
        if self.observer_pool:
            await self.observer_pool.stop()
            self.logger.debug("Пул наблюдателя остановлен")
        
        # 3. Горячий пул
        if self.hot_pool:
            await self.hot_pool.stop()
            self.logger.debug("Горячий пул остановлен")
        
        # 4. WebSocket сервер
        if self.websocket_server:
            await self.websocket_server.stop()
            self.logger.debug("WebSocket сервер остановлен")
        
        # Отключаем биржи
        for exchange_name, exchange in self.exchanges.items():
            try:
                await exchange.disconnect()
                self.logger.debug(f"Биржа {exchange_name} отключена")
            except Exception as e:
                self.logger.error(f"Ошибка отключения биржи {exchange_name}: {e}")
        
        self.exchanges.clear()
        self.logger.finish_operation("остановка системы", success=True)
    
    async def get_system_stats(self) -> Dict:
        """Получить статистику системы"""
        stats = {
            "orchestrator": {
                "is_running": self.is_running,
                "primary_scan_completed": self.primary_scan_completed,
                "exchanges_count": len(self.exchanges),
                "exchanges": list(self.exchanges.keys())
            }
        }
        
        # Статистика пулов (только если они существуют)
        if self.general_pool:
            stats["general_pool"] = self.general_pool.get_stats()
        
        if self.observer_pool:
            stats["observer_pool"] = self.observer_pool.get_stats()
        
        if self.hot_pool:
            stats["hot_pool"] = self.hot_pool.get_stats()
        
        # Статистика бирж
        stats["exchanges_stats"] = {}
        for name, exchange in self.exchanges.items():
            try:
                stats["exchanges_stats"][name] = exchange.get_stats()
            except:
                stats["exchanges_stats"][name] = {"status": "error"}
        
        return stats
    
    async def run_continuous_mode(self):
        """Запуск в режиме непрерывной работы"""
        self.logger.start_operation("непрерывный режим мониторинга")
        
        try:
            # Полный запуск системы
            await self.start()
            
            # Основной цикл мониторинга (упрощенный, без избыточного логирования)
            stats_counter = 0
            while self.is_running:
                try:
                    # Периодически выводим ключевые метрики (каждые 60 секунд)
                    if stats_counter % 60 == 0:
                        stats = await self.get_system_stats()
                        
                        hot_pool_stats = stats.get("hot_pool", {})
                        observer_stats = stats.get("observer_pool", {})
                        
                        # Логируем только ключевые метрики
                        hot_orders = hot_pool_stats.get("total_orders", 0)
                        observer_orders = observer_stats.get("total_orders", 0)
                        hot_symbols = hot_pool_stats.get("active_symbols", 0)
                        
                        self.logger.stats("система", 
                                        горячих_ордеров=hot_orders,
                                        наблюдаемых=observer_orders,
                                        символов=hot_symbols)
                        
                        # Показываем распределение категорий если есть горячие ордера
                        categories = hot_pool_stats.get("categories_distribution", {})
                        if categories and sum(categories.values()) > 0:
                            diamond_count = categories.get("diamond", 0)
                            gold_count = categories.get("gold", 0)
                            basic_count = categories.get("basic", 0)
                            
                            if diamond_count > 0:
                                log_hot_pool_update(diamond_count, gold_count, basic_count)
                    
                    stats_counter += 1
                    await asyncio.sleep(1)
                    
                except Exception as e:
                    self.logger.error(f"Ошибка в цикле мониторинга: {e}")
                    await asyncio.sleep(5)
                    
        except Exception as e:
            self.logger.error(f"Ошибка непрерывного режима: {e}")
            raise
