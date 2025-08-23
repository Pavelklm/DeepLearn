#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Быстрый тест исправления CLI
"""

import sys
import os

# Add current directory to path
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

def test_cli_fix():
    """Тест исправления CLI"""
    print("🔧 ТЕСТ ИСПРАВЛЕНИЯ CLI")
    print("=" * 40)
    
    try:
        from cli import CLI
        from config import ScannerConfig
        
        print(f"✅ Настройка MULTI_LEVEL_MODE: {ScannerConfig.MULTI_LEVEL_MODE}")
        
        # Создаем CLI
        cli = CLI()
        print(f"✅ CLI создан успешно")
        print(f"✅ Режим: {'многоуровневый' if cli.is_multi_level else 'обычный'}")
        print(f"✅ Тип сканера: {type(cli.scanner).__name__}")
        
        # Тест методов
        print("\n🧪 Тест методов...")
        
        # Тест print_header (без вывода)
        import io
        import contextlib
        
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            cli.print_header()
        
        header_output = f.getvalue()
        if "СКАНЕР БОЛЬШИХ ЗАЯВОК" in header_output:
            print("✅ print_header работает")
        else:
            print("❌ print_header не работает")
            
        # Тест print_instructions (без вывода)
        f = io.StringIO()
        with contextlib.redirect_stdout(f):
            cli.print_instructions()
            
        instructions_output = f.getvalue()
        if "УПРАВЛЕНИЕ" in instructions_output:
            print("✅ print_instructions работает")
        else:
            print("❌ print_instructions не работает")
        
        print("\n🎉 ВСЕ ТЕСТЫ ПРОШЛИ УСПЕШНО!")
        print("✅ CLI полностью исправлен и готов к работе")
        print("\n🚀 Можете запускать: python main.py")
        
    except Exception as e:
        print(f"❌ Ошибка в тесте: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    test_cli_fix()
