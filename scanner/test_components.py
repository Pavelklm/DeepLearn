#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Простой тест компонентов перед запуском
"""

import sys
import os

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

def test_imports():
    """Тестируем импорты всех компонентов"""
    print("🧪 ТЕСТ ИМПОРТОВ КОМПОНЕНТОВ")
    print("=" * 50)
    
    try:
        print("📦 Тестируем config...")
        from config import ScannerConfig
        print(f"   ✅ Config загружен, MULTI_LEVEL_MODE = {ScannerConfig.MULTI_LEVEL_MODE}")
        
        print("📦 Тестируем api_client...")
        from api_client import BinanceAPIClient
        print("   ✅ BinanceAPIClient импортирован")
        
        print("📦 Тестируем data_models...")
        from data_models import OrderData, SymbolResult
        print("   ✅ Data models импортированы")
        
        print("📦 Тестируем symbol_manager...")
        from symbol_manager import SymbolManager
        print("   ✅ SymbolManager импортирован")
        
        print("📦 Тестируем metrics_calculator...")
        from metrics_calculator import MetricsCalculator
        print("   ✅ MetricsCalculator импортирован")
        
        print("📦 Тестируем order_analyzer...")
        from order_analyzer import OrderAnalyzer
        print("   ✅ OrderAnalyzer импортирован")
        
        print("📦 Тестируем data_storage...")
        from data_storage import DataStorage
        print("   ✅ DataStorage импортирован")
        
        print("📦 Тестируем scanner...")
        from scanner import BinanceBigOrdersScanner
        print("   ✅ BinanceBigOrdersScanner импортирован")
        
        print("📦 Тестируем pool_manager...")
        from pool_manager import PoolManager
        print("   ✅ PoolManager импортирован")
        
        print("📦 Тестируем multi_level_scanner...")
        from multi_level_scanner import MultiLevelScanner
        print("   ✅ MultiLevelScanner импортирован")
        
        print("📦 Тестируем cli...")
        from cli import CLI
        print("   ✅ CLI импортирован")
        
        print("\n✅ ВСЕ ИМПОРТЫ УСПЕШНЫ!")
        return True
        
    except Exception as e:
        print(f"\n❌ Ошибка импорта: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_cli_creation():
    """Тестируем создание CLI"""
    print("\n🧪 ТЕСТ СОЗДАНИЯ CLI")
    print("=" * 50)
    
    try:
        from cli import CLI
        from config import ScannerConfig
        
        print(f"⚙️ Режим: {'многоуровневый' if ScannerConfig.MULTI_LEVEL_MODE else 'обычный'}")
        
        # Создаем CLI объект
        cli = CLI()
        print("✅ CLI объект создан успешно")
        print(f"✅ Атрибут is_multi_level: {cli.is_multi_level}")
        print(f"✅ Тип сканера: {type(cli.scanner).__name__}")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка создания CLI: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """Главная функция тестирования"""
    print("🚀 ПОЛНЫЙ ТЕСТ КОМПОНЕНТОВ ПЕРЕД ЗАПУСКОМ")
    print("=" * 60)
    
    success = True
    
    # Тест 1: Импорты
    if not test_imports():
        success = False
    
    # Тест 2: Создание CLI
    if success and not test_cli_creation():
        success = False
    
    print("\n" + "=" * 60)
    if success:
        print("🎉 ВСЕ ТЕСТЫ ПРОШЛИ УСПЕШНО!")
        print("✅ Система готова к запуску")
        print("\n🚀 КОМАНДЫ ДЛЯ ЗАПУСКА:")
        print("   python main.py           - Запуск сканера")
        print("   python test_multi_level.py - Дополнительное тестирование")
    else:
        print("❌ ЕСТЬ ПРОБЛЕМЫ В СИСТЕМЕ")
        print("🔧 Исправьте ошибки перед запуском")
    
    print("=" * 60)
    return success

if __name__ == "__main__":
    main()
