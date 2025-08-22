#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI интерфейс для сканера больших ордеров - упрощенная версия
"""

import sys
import os

# Add current directory to path for absolute imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

try:
    from scanner import BinanceBigOrdersScanner
    from config import ScannerConfig
except ImportError:
    try:
        from .scanner import BinanceBigOrdersScanner
        from .config import ScannerConfig
    except ImportError:
        # If both fail, try importing from the same directory
        import scanner as scanner_module
        import config as config_module
        BinanceBigOrdersScanner = scanner_module.BinanceBigOrdersScanner
        ScannerConfig = config_module.ScannerConfig


class CLI:
    """Упрощенный интерфейс командной строки для сканера"""
    
    def __init__(self):
        self.scanner = BinanceBigOrdersScanner()
        # Настраиваем оптимальный режим работы
        self.scanner.set_persistent_mode(True)  # Персистентное хранение
        self.scanner.set_verbose_logs(True)     # Детальные логи
    
    def print_header(self):
        """Выводим заголовок программы"""
        print("=" * 80)
        print("🚀 СКАНЕР БОЛЬШИХ ЗАЯВОК BINANCE FUTURES")
        print("=" * 80)
        print(f"💰 Минимальный размер ордера: ${ScannerConfig.MIN_ORDER_SIZE_USD:,}")
        print(f"🚫 Исключенные символы: {', '.join(ScannerConfig.EXCLUDED_SYMBOLS)}")
        print(f"📊 Ограничения: макс {ScannerConfig.MAX_ORDERS_PER_SIDE}+{ScannerConfig.MAX_ORDERS_PER_SIDE} ордера/символ, динамический радиус (волатильность x{ScannerConfig.VOLATILITY_MULTIPLIER})")
        print(f"🔥 Режим: ПЕРСИСТЕНТНОЕ ХРАНЕНИЕ + НЕПРЕРЫВНОЕ СКАНИРОВАНИЕ")
        print(f"⚡ Параллельные запросы: {ScannerConfig.MAX_WORKERS} воркеров")
        print(f"📈 Фильтрация: топ-{ScannerConfig.TOP_SYMBOLS_COUNT} пар по объему торгов")
        print()
        print("✅ Отслеживание времени жизни ордеров")
        print("✅ Различение новых и существующих ордеров") 
        print("✅ Сохранение данных между итерациями")
        print("✅ Автоматическое удаление исчезнувших ордеров")
        print("✅ BATCH оптимизация API запросов")
        print("✅ Retry логика для надежности")
        print(f"✅ Динамический радиус поиска (коэф. {ScannerConfig.VOLATILITY_MULTIPLIER})")
        print("=" * 80)
    
    def print_instructions(self):
        """Выводим инструкции по управлению"""
        print("🎮 УПРАВЛЕНИЕ:")
        print("   Ctrl+C - остановка сканирования")
        print("   Программа работает в непрерывном режиме")
        print("   Подсказка: v:волатильность%, r:радиус поиска ±%")
        print("=" * 80)
    
    def run(self):
        """Основной метод запуска CLI"""
        try:
            self.print_header()
            self.print_instructions()
            
            print("🚀 Запуск непрерывного сканирования...")
            print("   Данные сохраняются в:", self.scanner.data_storage.data_file)
            print()
            
            # Запускаем непрерывное сканирование
            self.scanner.continuous_scan()
                
        except KeyboardInterrupt:
            print("\n" + "=" * 80)
            print("🛑 Программа остановлена пользователем")
            print("💾 Все данные сохранены")
            print("=" * 80)
        except Exception as e:
            print(f"\n❌ Критическая ошибка: {e}")
            print("💾 Попытка сохранения данных...")
