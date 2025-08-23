#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Временное отключение многоуровневого режима для тестирования
"""

import sys
import os

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

def disable_multi_level_mode():
    """Временно отключаем многоуровневый режим"""
    config_path = "config.py"
    
    try:
        # Читаем файл
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Заменяем MULTI_LEVEL_MODE = True на False
        content = content.replace('MULTI_LEVEL_MODE = True', 'MULTI_LEVEL_MODE = False')
        
        # Записываем обратно
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print("✅ Многоуровневый режим ОТКЛЮЧЕН")
        print("🔄 Переключено на обычное сканирование")
        print("\n🚀 Теперь можно запускать: python main.py")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка отключения: {e}")
        return False

def enable_multi_level_mode():
    """Включаем многоуровневый режим обратно"""
    config_path = "config.py"
    
    try:
        # Читаем файл
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Заменяем MULTI_LEVEL_MODE = False на True
        content = content.replace('MULTI_LEVEL_MODE = False', 'MULTI_LEVEL_MODE = True')
        
        # Записываем обратно
        with open(config_path, 'w', encoding='utf-8') as f:
            f.write(content)
        
        print("✅ Многоуровневый режим ВКЛЮЧЕН")
        print("🚀 Готов к многоуровневому сканированию")
        
        return True
        
    except Exception as e:
        print(f"❌ Ошибка включения: {e}")
        return False

def main():
    """Главная функция"""
    print("🔧 ПЕРЕКЛЮЧАТЕЛЬ РЕЖИМОВ СКАНИРОВАНИЯ")
    print("=" * 50)
    
    from config import ScannerConfig
    current_mode = "многоуровневый" if ScannerConfig.MULTI_LEVEL_MODE else "обычный"
    print(f"📊 Текущий режим: {current_mode}")
    
    print("\nВыберите действие:")
    print("1 - Отключить многоуровневый режим (временно)")
    print("2 - Включить многоуровневый режим")
    print("3 - Показать текущий статус")
    
    choice = input("\nВаш выбор (1-3): ").strip()
    
    if choice == "1":
        disable_multi_level_mode()
    elif choice == "2":
        enable_multi_level_mode()
    elif choice == "3":
        print(f"📊 Текущий режим: {current_mode}")
    else:
        print("❌ Неверный выбор")

if __name__ == "__main__":
    main()
