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
    from multi_level_scanner import MultiLevelScanner
    from config import ScannerConfig
except ImportError:
    try:
        from .scanner import BinanceBigOrdersScanner
        from .multi_level_scanner import MultiLevelScanner
        from .config import ScannerConfig
    except ImportError:
        # If both fail, try importing from the same directory
        import scanner as scanner_module
        import multi_level_scanner as multi_level_scanner_module
        import config as config_module
        BinanceBigOrdersScanner = scanner_module.BinanceBigOrdersScanner
        MultiLevelScanner = multi_level_scanner_module.MultiLevelScanner
        ScannerConfig = config_module.ScannerConfig


class CLI:
    """Упрощенный интерфейс командной строки для сканера"""
    
    def __init__(self):
        # Выбираем тип сканера в зависимости от настроек
        if ScannerConfig.MULTI_LEVEL_MODE:
            self.scanner = MultiLevelScanner()
            self.is_multi_level = True
        else:
            self.scanner = BinanceBigOrdersScanner()
            # Настраиваем оптимальный режим работы
            self.scanner.set_persistent_mode(True)  # Персистентное хранение
            self.scanner.set_verbose_logs(True)     # Детальные логи
            self.is_multi_level = False
    
    def print_header(self):
        """Выводим заголовок программы"""
        mode_text = "МНОГОУРОВНЕВЫЙ" if self.is_multi_level else "ОБЫЧНЫЙ"
        print("=" * 80)
        print(f"🚀 СКАНЕР БОЛЬШИХ ЗАЯВОК BINANCE FUTURES - {mode_text} РЕЖИМ")
        print("=" * 80)
        print(f"💰 Коэффициент китов: {ScannerConfig.WHALE_MULTIPLIER}x (средний_ордер * коэффициент)")
        print(f"🚫 Исключенные символы: {', '.join(ScannerConfig.EXCLUDED_SYMBOLS)}")
        print(f"📊 Ограничения: макс {ScannerConfig.MAX_ORDERS_PER_SIDE}+{ScannerConfig.MAX_ORDERS_PER_SIDE} ордера/символ, динамический радиус (волатильность x{ScannerConfig.VOLATILITY_MULTIPLIER})")
        
        if self.is_multi_level:
            print(f"🔥 МНОГОУРОВНЕВЫЙ РЕЖИМ:")
            print(f"   🔥 Горячий пул: {ScannerConfig.HOT_POOL_WORKERS} воркеров + 1 выделенный")
            print(f"   📋 Пул наблюдения: {ScannerConfig.WATCH_POOL_WORKER} воркер, каждые {ScannerConfig.WATCH_SCAN_INTERVAL}сек, макс {ScannerConfig.WATCH_MAX_SCANS} сканов")
            print(f"   📊 Общий пул: {ScannerConfig.GENERAL_POOL_WORKERS} воркеров, каждые {ScannerConfig.GENERAL_SCAN_INTERVAL}сек")
        else:
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
        
        if self.is_multi_level:
            print("✅ Интеллектуальное распределение нагрузки по пулам")
            print("✅ Автоматическое перемещение символов между пулами")
            print("✅ Оптимизированное использование API")
        
        print("=" * 80)
    
    def print_instructions(self):
        """Выводим инструкции по управлению"""
        print("🎮 УПРАВЛЕНИЕ:")
        print("   Ctrl+C - остановка сканирования")
        
        if self.is_multi_level:
            print("   Программа работает в многоуровневом режиме")
            print("   Статус пулов обновляется каждую минуту")
        else:
            print("   Программа работает в непрерывном режиме")
        
        print("   Подсказка: v:волатильность%, r:радиус поиска ±%")
        print("=" * 80)
    
    def run(self):
        """Основной метод запуска CLI"""
        try:
            self.print_header()
            self.print_instructions()
            
            if self.is_multi_level:
                print("🚀 Запуск многоуровневого сканирования...")
                print("   Данные сохраняются в:", self.scanner.base_scanner.data_storage.data_file)
                print()
                
                # Запускаем многоуровневое сканирование
                self.scanner.start_multi_level_scanning()
            else:
                print("🚀 Запуск непрерывного сканирования...")
                print("   Данные сохраняются в:", self.scanner.data_storage.data_file)
                print()
                
                # Запускаем обычное непрерывное сканирование
                self.scanner.continuous_scan()
                
        except KeyboardInterrupt:
            print("\n" + "=" * 80)
            print("🛑 Программа остановлена пользователем")
            print("💾 Все данные сохранены")
            print("=" * 80)
        except Exception as e:
            print(f"\n❌ Критическая ошибка: {e}")
            print("💾 Попытка сохранения данных...")
