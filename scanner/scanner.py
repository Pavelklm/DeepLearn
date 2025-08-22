#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Основной класс сканера больших ордеров
"""

import time
from typing import List, Tuple
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .api_client import BinanceAPIClient
from .symbol_manager import SymbolManager
from .metrics_calculator import MetricsCalculator
from .order_analyzer import OrderAnalyzer
from .data_storage import DataStorage
from .data_models import SymbolResult
from .config import ScannerConfig


class BinanceBigOrdersScanner:
    """Основной класс сканера больших ордеров на Binance Futures"""
    
    def __init__(self):
        # Инициализация компонентов
        self.api_client = BinanceAPIClient()
        self.symbol_manager = SymbolManager(self.api_client)
        self.metrics_calculator = MetricsCalculator(self.api_client)
        self.order_analyzer = OrderAnalyzer()
        self.data_storage = DataStorage()
        
        # Настройки из конфигурации
        self.max_workers = ScannerConfig.MAX_WORKERS
        self.persistent_mode = ScannerConfig.PERSISTENT_MODE
        self.verbose_logs = ScannerConfig.VERBOSE_LOGS
        self.first_run = True
    
    def set_verbose_logs(self, verbose: bool):
        """Устанавливаем режим детальных логов"""
        self.verbose_logs = verbose
        ScannerConfig.VERBOSE_LOGS = verbose
        self.symbol_manager.verbose_logs = verbose
        self.data_storage.verbose_logs = verbose
    
    def set_persistent_mode(self, persistent: bool):
        """Устанавливаем режим персистентности"""
        self.persistent_mode = persistent
        ScannerConfig.PERSISTENT_MODE = persistent
    
    def process_symbol_with_index(self, symbol_task: tuple) -> int:
        """Обрабатываем один символ с индексом (и batch ticker данными)"""
        symbol, index, total, ticker_data = symbol_task
        try:
            if self.verbose_logs:
                print(f"Сканирование {symbol} ({index}/{total})")
            
            # Получаем полные данные символа (используя batch ticker)
            symbol_data = self.metrics_calculator.get_symbol_data(symbol, ticker_data)
            if not symbol_data:
                return 0
            
            # Получаем стакан ордеров
            order_book = self.api_client.get_order_book(symbol)
            if not order_book:
                return 0
            
            # Рассчитываем метрики символа
            symbol_metrics = self.metrics_calculator.calculate_symbol_metrics(symbol_data, order_book)
            
            # Ищем большие ордера
            big_orders = self.order_analyzer.find_big_orders(symbol, order_book, symbol_data, symbol_metrics)
            
            if big_orders:
                # Логирование найденных ордеров
                total_usd = sum(order.usd_value for order in big_orders)
                bid_count = len([o for o in big_orders if o.type == 'BID'])
                ask_count = len([o for o in big_orders if o.type == 'ASK'])
                price_str = f"${symbol_data.current_price:.4f}"
                print(f"💰 {symbol:<12} | {price_str:<12} | 🟢{bid_count}B/🔴{ask_count}A | ${total_usd:>8,.0f}")
                
                # Создаем результат обработки символа
                symbol_result = SymbolResult(
                    symbol=symbol,
                    timestamp=datetime.now().isoformat(),
                    current_price=symbol_data.current_price,
                    volatility_1h=symbol_metrics.volatility_1h,
                    volume_ratio=symbol_metrics.volume_ratio,
                    price_movement_5min=symbol_metrics.price_movement_5min,
                    is_round_level=symbol_metrics.is_round_level,
                    orders_count=len(big_orders),
                    orders=big_orders
                )
                
                # Сохраняем данные
                self.save_symbol_data(symbol_result)
                return len(big_orders)
            
            return 0
            
        except Exception as e:
            print(f"Ошибка обработки {symbol}: {e}")
            return 0
    
    def save_symbol_data(self, symbol_result: SymbolResult):
        """Сохраняем данные символа в зависимости от режима"""
        if self.persistent_mode:
            self.data_storage.save_symbol_data_persistent(symbol_result)
        else:
            self.data_storage.save_symbol_data_simple(symbol_result)
    
    def scan_all_symbols(self):
        """Основной метод сканирования топ-250 символов с BATCH оптимизацией"""
        mode_text = "ПЕРСИСТЕНТНЫМ" if self.persistent_mode else "ОБЫЧНЫМ"
        
        if self.first_run:
            print(f"🚀 Начало сканирования в {mode_text} режиме ({self.max_workers} воркеров)")
            
            # Очищаем файл ТОЛЬКО при первом запуске
            if not self.persistent_mode:
                self.data_storage.clear_data_file()
                print("🗑️ Очищены старые данные (обычный режим)")
            else:
                print("💾 Персистентный режим: сохраняем существующие данные")
            
            self.first_run = False  # Отмечаем, что первый запуск завершен
        else:
            # Последующие итерации - компактное логирование
            print(f"🔄 Новая итерация...")
        
        # Получаем отфильтрованные символы и их ticker данные
        filtered_symbols, all_tickers = self.symbol_manager.get_filtered_symbols()
        if not filtered_symbols or not all_tickers:
            print("Не удалось получить символы или ticker данные")
            return
        
        total_big_orders = 0
        
        # Создаем кортежи (символ, индекс, общее_количество, ticker_data) для отфильтрованных символов
        symbol_tasks = []
        for i, symbol in enumerate(filtered_symbols):
            ticker_data = all_tickers.get(symbol)  # Получаем ticker данные для символа
            if ticker_data:  # Обрабатываем только символы с ticker данными
                symbol_tasks.append((symbol, i+1, len(filtered_symbols), ticker_data))
        
        print(f"🚀 Обрабатываем {len(symbol_tasks)} символов ({ScannerConfig.MAX_WORKERS} воркеров)...")
        
        # Для отслеживания прогресса
        symbols_with_orders = 0
        
        # Заголовок для таблицы результатов
        if self.verbose_logs:
            print(f"\n{'='*70}")
            print(f"{'СИМВОЛ':<12} | {'ЦЕНА':<12} | {'ОРДЕРА':<8} | {'ОБЪЕМ':<12}")
            print(f"{'='*70}")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            results = executor.map(self.process_symbol_with_index, symbol_tasks)
            for result in results:
                total_big_orders += result
                if result > 0:
                    symbols_with_orders += 1
        
        # Подсчитываем статистику
        total_symbols_processed = len(symbol_tasks)
        success_rate = (total_symbols_processed / len(filtered_symbols)) * 100 if filtered_symbols else 0
        
        print(f"\n{'-'*70}")
        print(f"🏁 Сканирование завершено!")
        print(f"📊 Обработано символов: {total_symbols_processed}/{len(filtered_symbols)} ({success_rate:.1f}%)")
        print(f"🎯 Символов с ордерами: {symbols_with_orders}")
        print(f"💰 Найдено больших ордеров: {total_big_orders}")
        if self.verbose_logs:
            print(f"💾 Данные сохранены: {self.data_storage.data_file}")
    
    def continuous_scan(self):
        """Непрерывное сканирование с оптимальным логированием"""
        print(f"\n🔄 Непрерывное сканирование запущено!")
        print(f"💾 Данные сохраняются в: {self.data_storage.data_file}")
        
        iteration = 1
        start_time = time.time()
        
        while True:
            try:
                iteration_start = time.time()
                print(f"\n{'='*60}")
                print(f"🔄 ИТЕРАЦИЯ #{iteration} | {datetime.now().strftime('%H:%M:%S')}")
                print(f"{'='*60}")
                
                self.scan_all_symbols()
                
                iteration_time = time.time() - iteration_start
                total_time = time.time() - start_time
                
                print(f"\n✅ Итерация #{iteration} завершена за {iteration_time:.1f}с")
                print(f"🕰️ Общее время работы: {total_time/60:.1f} мин")
                
                iteration += 1
                
            except KeyboardInterrupt:
                print(f"\n\n{'='*60}")
                print("🛱 Остановка по запросу пользователя")
                print(f"📊 Выполнено итераций: {iteration-1}")
                total_time = time.time() - start_time
                print(f"🕰️ Общее время работы: {total_time/60:.1f} мин")
                print(f"{'='*60}")
                break
            except Exception as e:
                print(f"\n⚠️ Ошибка в итерации #{iteration}: {e}")
                print("🔄 Повторная попытка через 30 секунд...")
                time.sleep(30)
