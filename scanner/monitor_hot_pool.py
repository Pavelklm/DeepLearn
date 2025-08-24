#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Отладочный монитор горячего пула
"""

import json
import os
import time
from datetime import datetime

def monitor_whale_symbols():
    """Мониторинг изменений в whale_symbols.json"""
    whale_file = "whale_symbols.json"
    previous_symbols = set()
    
    print("🔍 МОНИТОР ГОРЯЧЕГО ПУЛА")
    print("=" * 50)
    print("Отслеживаем изменения в whale_symbols.json...")
    print("Нажмите Ctrl+C для остановки")
    print()
    
    try:
        while True:
            if os.path.exists(whale_file):
                try:
                    with open(whale_file, 'r', encoding='utf-8') as f:
                        whale_data = json.load(f)
                    
                    current_symbols = {item['symbol'] for item in whale_data}
                    
                    # Проверяем изменения
                    added = current_symbols - previous_symbols
                    removed = previous_symbols - current_symbols
                    
                    if added or removed or not previous_symbols:
                        timestamp = datetime.now().strftime("%H:%M:%S")
                        print(f"[{timestamp}] 📊 Горячий пул: {len(current_symbols)} символов")
                        
                        if added:
                            print(f"  ➕ Добавлены: {list(added)}")
                        if removed:
                            print(f"  ➖ Удалены: {list(removed)}")
                        
                        if current_symbols:
                            print(f"  📋 Текущие: {sorted(list(current_symbols))}")
                        print()
                    
                    previous_symbols = current_symbols.copy()
                    
                except json.JSONDecodeError:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ⚠️ Ошибка чтения JSON")
                except Exception as e:
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ Ошибка: {e}")
            else:
                if previous_symbols:
                    timestamp = datetime.now().strftime("%H:%M:%S")
                    print(f"[{timestamp}] 🗑️ Файл whale_symbols.json удален")
                    previous_symbols = set()
            
            time.sleep(2)  # Проверяем каждые 2 секунды
            
    except KeyboardInterrupt:
        print("\n🛑 Мониторинг остановлен")

if __name__ == "__main__":
    monitor_whale_symbols()
