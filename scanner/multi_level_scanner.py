#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Многоуровневый сканер больших ордеров
"""

import time
import threading
from typing import List, Set
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

try:
    from scanner import BinanceBigOrdersScanner
    from pool_manager import PoolManager, PoolType
    from config import ScannerConfig
    from symbol_manager import SymbolManager
    from api_client import BinanceAPIClient
except ImportError:
    from .scanner import BinanceBigOrdersScanner
    from .pool_manager import PoolManager, PoolType
    from .config import ScannerConfig
    from .symbol_manager import SymbolManager
    from .api_client import BinanceAPIClient


class MultiLevelScanner:
    """Многоуровневый сканер с тремя пулами"""
    
    def __init__(self):
        # Базовые компоненты
        self.base_scanner = BinanceBigOrdersScanner()
        self.pool_manager = PoolManager()
        self.api_client = BinanceAPIClient()
        self.symbol_manager = SymbolManager(self.api_client)
        
        # Настройки из конфигурации
        self.verbose_logs = ScannerConfig.VERBOSE_LOGS
        self.multi_level_mode = ScannerConfig.MULTI_LEVEL_MODE
        self.initial_full_scan = ScannerConfig.INITIAL_FULL_SCAN
        
        # Состояние
        self._stop_event = threading.Event()
        self._threads = []
        self._all_symbols_cache = []
        self._last_symbols_update = None
        
        # Статистика
        self.stats = {
            'hot_scans': 0,
            'watch_scans': 0,
            'general_scans': 0,
            'symbols_moved_to_watch': 0,
            'symbols_moved_to_general': 0,
            'symbols_returned_to_hot': 0
        }
    
    def set_verbose_logs(self, verbose: bool):
        """Устанавливаем режим детальных логов"""
        self.verbose_logs = verbose
        self.base_scanner.set_verbose_logs(verbose)
    
    def get_all_symbols(self) -> List[str]:
        """Получаем кэшированный список всех символов"""
        now = datetime.now()
        
        # Обновляем кэш каждые 5 минут
        if (not self._last_symbols_update or 
            (now - self._last_symbols_update).total_seconds() > 300):
            
            filtered_symbols, _ = self.symbol_manager.get_filtered_symbols()
            if filtered_symbols:
                self._all_symbols_cache = filtered_symbols
                self._last_symbols_update = now
                print(f"🔄 Обновлен кэш символов: {len(self._all_symbols_cache)} символов")
        
        return self._all_symbols_cache
    
    def run_initial_full_scan(self):
        """Выполняем полный начальный скан для заполнения горячего пула"""
        print(f"\n{'='*80}")
        print("🚀 НАЧАЛЬНЫЙ ПОЛНЫЙ СКАН")
        print(f"{'='*80}")
        
        # Очищаем старые данные
        self.base_scanner.data_storage.clear_data_file()
        
        # Выполняем полный скан базовым сканером
        self.base_scanner.scan_all_symbols()
        
        # Получаем статистику
        hot_symbols = self.pool_manager.get_hot_pool_symbols()
        print(f"🔥 Найдено активных символов с китами: {len(hot_symbols)}")
        
        if hot_symbols and self.verbose_logs:
            print("   Горячий пул:", ', '.join(sorted(hot_symbols)))
        
        print(f"✅ Начальный скан завершен, переходим в многоуровневый режим")
    
    def hot_pool_worker(self):
        """Воркер для непрерывного сканирования горячего пула"""
        print(f"🔥 Запущен воркер горячего пула")
        
        while not self._stop_event.is_set():
            try:
                hot_symbols = list(self.pool_manager.get_hot_pool_symbols())
                
                if not hot_symbols:
                    if self.verbose_logs:
                        print("🔥 Горячий пул пуст, ждем...")
                    self._stop_event.wait(5)  # Используем wait вместо sleep
                    continue
                
                scan_start = time.time()
                symbols_scanned = 0
                orders_found = 0
                
                print(f"\n🔥 ГОРЯЧИЙ ПУЛ: Сканирование {len(hot_symbols)} символов...")
                
                # ОПТИМИЗАЦИЯ: Получаем ticker данные ОДИН раз для всех символов горячего пула
                try:
                    all_tickers = self.symbol_manager.get_all_tickers_batch()
                    if not all_tickers:
                        print("⚠️ Не удалось получить ticker данные, пропускаем итерацию")
                        continue
                except Exception as e:
                    print(f"⚠️ Ошибка получения ticker данных: {e}")
                    continue
                
                # Сканируем каждый символ в горячем пуле
                for i, symbol in enumerate(hot_symbols, 1):
                    if self._stop_event.is_set():
                        break
                    
                    # Используем метод базового сканера для обработки символа
                    try:
                        if symbol not in all_tickers:
                            continue
                        
                        ticker_data = all_tickers[symbol]
                        result = self.base_scanner.process_symbol_with_index(
                            (symbol, i, len(hot_symbols), ticker_data)
                        )
                        
                        if result > 0:
                            orders_found += result
                        symbols_scanned += 1
                        self.stats['hot_scans'] += 1
                        
                    except Exception as e:
                        if self.verbose_logs:
                            print(f"🔥 Ошибка сканирования {symbol}: {e}")
                
                scan_time = time.time() - scan_start
                
                # Проверяем изменения в горячем пуле
                lost_symbols = self.pool_manager.check_hot_pool_changes()
                for symbol in lost_symbols:
                    self.pool_manager.add_to_watch_pool(symbol)
                    self.stats['symbols_moved_to_watch'] += 1
                
                # Логирование результатов
                print(f"🔥 Горячий скан: {symbols_scanned} символов за {scan_time:.1f}с, найдено {orders_found} ордеров")
                if lost_symbols:
                    print(f"📋 Переведено в наблюдение: {len(lost_symbols)} символов")
                
                # Короткая пауза между сканами горячего пула
                if not self._stop_event.is_set():
                    self._stop_event.wait(2)
                
            except Exception as e:
                print(f"🔥 Ошибка в воркере горячего пула: {e}")
                if not self._stop_event.is_set():
                    self._stop_event.wait(5)
    
    def watch_pool_worker(self):
        """Воркер для сканирования пула наблюдения"""
        print(f"📋 Запущен воркер пула наблюдения")
        
        while not self._stop_event.is_set():
            try:
                watch_symbols = list(self.pool_manager.get_watch_pool_symbols())
                
                if not watch_symbols:
                    time.sleep(ScannerConfig.WATCH_SCAN_INTERVAL)
                    continue
                
                print(f"📋 НАБЛЮДЕНИЕ: Проверяем {len(watch_symbols)} символов...")
                
                symbols_to_remove = []
                orders_found = 0
                
                for symbol in watch_symbols:
                    if self._stop_event.is_set():
                        break
                    
                    try:
                        # Проверяем символ
                        filtered_symbols, all_tickers = self.symbol_manager.get_filtered_symbols()
                        if symbol not in all_tickers:
                            continue
                        
                        ticker_data = all_tickers[symbol]
                        result = self.base_scanner.process_symbol_with_index(
                            (symbol, 1, 1, ticker_data)
                        )
                        
                        if result > 0:
                            orders_found += result
                            # Если нашли ордера - символ автоматически вернется в горячий пул
                            # через механизм data_storage
                        
                        # Увеличиваем счетчик сканов
                        should_move_to_general = self.pool_manager.increment_watch_scan(symbol)
                        if should_move_to_general:
                            symbols_to_remove.append(symbol)
                            self.stats['symbols_moved_to_general'] += 1
                        
                        self.stats['watch_scans'] += 1
                        
                    except Exception as e:
                        if self.verbose_logs:
                            print(f"📋 Ошибка сканирования наблюдения {symbol}: {e}")
                
                if orders_found > 0:
                    print(f"📋 Наблюдение: найдено {orders_found} ордеров")
                if symbols_to_remove:
                    print(f"📋 Переведено в общий пул: {len(symbols_to_remove)} символов")
                
                # Очистка устаревших символов
                self.pool_manager.cleanup_expired_watch_symbols()
                
                time.sleep(ScannerConfig.WATCH_SCAN_INTERVAL)
                
            except Exception as e:
                print(f"📋 Ошибка в воркере наблюдения: {e}")
                time.sleep(ScannerConfig.WATCH_SCAN_INTERVAL)
    
    def general_pool_worker(self):
        """Воркер для сканирования общего пула"""
        print(f"📊 Запущен воркер общего пула")
        
        while not self._stop_event.is_set():
            try:
                all_symbols = self.get_all_symbols()
                general_symbols = self.pool_manager.get_general_pool_symbols(all_symbols)
                
                if not general_symbols:
                    time.sleep(ScannerConfig.GENERAL_SCAN_INTERVAL)
                    continue
                
                scan_start = time.time()
                print(f"📊 ОБЩИЙ ПУЛ: Сканирование {len(general_symbols)} символов...")
                
                # Используем многопоточность для общего пула
                orders_found = 0
                symbols_scanned = 0
                
                # Получаем ticker данные
                filtered_symbols, all_tickers = self.symbol_manager.get_filtered_symbols()
                
                # Создаем задачи для воркеров
                symbol_tasks = []
                for i, symbol in enumerate(general_symbols):
                    if symbol in all_tickers:
                        ticker_data = all_tickers[symbol]
                        symbol_tasks.append((symbol, i+1, len(general_symbols), ticker_data))
                
                # Сканируем с использованием пула потоков
                with ThreadPoolExecutor(max_workers=ScannerConfig.GENERAL_POOL_WORKERS) as executor:
                    results = executor.map(self.base_scanner.process_symbol_with_index, symbol_tasks)
                    for result in results:
                        if self._stop_event.is_set():
                            break
                        orders_found += result
                        symbols_scanned += 1
                        self.stats['general_scans'] += 1
                
                scan_time = time.time() - scan_start
                print(f"📊 Общий скан: {symbols_scanned} символов за {scan_time:.1f}с, найдено {orders_found} ордеров")
                
                time.sleep(ScannerConfig.GENERAL_SCAN_INTERVAL)
                
            except Exception as e:
                print(f"📊 Ошибка в воркере общего пула: {e}")
                time.sleep(ScannerConfig.GENERAL_SCAN_INTERVAL)
    
    def print_status(self):
        """Выводим статус системы"""
        pools_status = self.pool_manager.get_pools_status()
        
        print(f"\n{'='*80}")
        print(f"📊 СТАТУС МНОГОУРОВНЕВОГО СКАНЕРА")
        print(f"{'='*80}")
        print(f"🔥 Горячий пул:    {pools_status['hot_pool']} символов")
        print(f"📋 Пул наблюдения: {pools_status['watch_pool']} символов")
        
        if pools_status['watch_symbols_details']:
            print(f"   └─ Детали: {', '.join(pools_status['watch_symbols_details'])}")
        
        general_count = len(self.get_all_symbols()) - pools_status['hot_pool'] - pools_status['watch_pool']
        print(f"📊 Общий пул:      {general_count} символов")
        
        print(f"\n📈 СТАТИСТИКА:")
        print(f"   🔥 Сканов горячего пула:    {self.stats['hot_scans']}")
        print(f"   📋 Сканов наблюдения:       {self.stats['watch_scans']}")
        print(f"   📊 Сканов общего пула:      {self.stats['general_scans']}")
        print(f"   ↗️ Переводов в наблюдение:   {self.stats['symbols_moved_to_watch']}")
        print(f"   ↘️ Переводов в общий пул:    {self.stats['symbols_moved_to_general']}")
        print(f"{'='*80}")
    
    def start_multi_level_scanning(self):
        """Запускаем многоуровневое сканирование"""
        print(f"\n{'='*80}")
        print("🚀 ЗАПУСК МНОГОУРОВНЕВОГО СКАНЕРА")
        print(f"{'='*80}")
        
        # Настройка базового сканера
        self.base_scanner.set_persistent_mode(True)
        self.base_scanner.set_verbose_logs(False)  # Отключаем детальные логи
        
        # Настройка symbol_manager для меньшей детализации
        self.symbol_manager.verbose_logs = False
        
        # Начальный полный скан
        if self.initial_full_scan:
            self.run_initial_full_scan()
        
        # Запускаем воркеры в отдельных потоках
        print(f"\n🔧 Запуск воркеров...")
        
        # Горячий пул воркер
        hot_thread = threading.Thread(target=self.hot_pool_worker, daemon=True)
        hot_thread.start()
        self._threads.append(hot_thread)
        
        # Пул наблюдения воркер  
        watch_thread = threading.Thread(target=self.watch_pool_worker, daemon=True)
        watch_thread.start()
        self._threads.append(watch_thread)
        
        # Общий пул воркер
        general_thread = threading.Thread(target=self.general_pool_worker, daemon=True)
        general_thread.start()
        self._threads.append(general_thread)
        
        print(f"✅ Все воркеры запущены")
        
        # Основной цикл мониторинга
        try:
            while not self._stop_event.is_set():
                self._stop_event.wait(60)  # Статус каждую минуту
                if not self._stop_event.is_set():
                    self.print_status()
                
        except KeyboardInterrupt:
            print(f"\n🛑 Получен сигнал остановки...")
            self.stop()
    
    def stop(self):
        """Останавливаем все воркеры"""
        print(f"🛑 Остановка многоуровневого сканера...")
        self._stop_event.set()
        
        # Ждем завершения потоков
        for thread in self._threads:
            thread.join(timeout=5)
        
        self.print_status()
        print(f"✅ Многоуровневый сканер остановлен")
