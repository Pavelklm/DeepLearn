#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CLI интерфейс для сканера больших ордеров - упрощенная версия
"""

from .scanner import BinanceBigOrdersScanner
from .config import ScannerConfig


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
        print(f"📊 Ограничения: макс {ScannerConfig.MAX_ORDERS_PER_SIDE}+{ScannerConfig.MAX_ORDERS_PER_SIDE} ордера/символ, макс {ScannerConfig.MAX_DISTANCE_PERCENT}% от цены")
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
        print("=" * 80)
    
    def print_instructions(self):
        """Выводим инструкции по управлению"""
        print("🎮 УПРАВЛЕНИЕ:")
        print("   Ctrl+C - остановка сканирования")
        print("   Программа работает в непрерывном режиме")
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
