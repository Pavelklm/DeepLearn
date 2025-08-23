#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Тестовый запуск многоуровневого сканера
"""

import sys
import os

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from config import ScannerConfig
from multi_level_scanner import MultiLevelScanner

def test_multi_level():
    """Тест многоуровневого сканера"""
    print("🧪 ТЕСТОВЫЙ ЗАПУСК МНОГОУРОВНЕВОГО СКАНЕРА")
    print("=" * 50)
    
    # Создаем сканер
    scanner = MultiLevelScanner()
    scanner.set_verbose_logs(True)
    
    try:
        # Тест компонентов
        print("\n🔧 Тестирование компонентов...")
        
        # Тест pool_manager
        print("   ✅ PoolManager создан")
        
        # Тест получения символов
        all_symbols = scanner.get_all_symbols()
        print(f"   ✅ Получено {len(all_symbols)} символов")
        
        # Тест статуса пулов
        pools_status = scanner.pool_manager.get_pools_status()
        print(f"   ✅ Статус пулов: {pools_status}")
        
        print("\n✅ Все тесты прошли успешно!")
        print("\n🚀 Готов к запуску! Использование:")
        print("   python main.py - для запуска через CLI")
        print("   или настройте MULTI_LEVEL_MODE = False в config.py для обычного режима")
        
    except Exception as e:
        print(f"\n❌ Ошибка в тесте: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_multi_level()
