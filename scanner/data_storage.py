#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Персистентное хранение данных ордеров
"""

import json
import os
import threading
from typing import List, Dict
from datetime import datetime

try:
    from data_models import SymbolResult, OrderData, OrderKey
    from config import ScannerConfig
except ImportError:
    from .data_models import SymbolResult, OrderData, OrderKey
    from .config import ScannerConfig


class DataStorage:
    """Класс для работы с персистентным хранением данных"""
    
    # Общий lock для всех экземпляров DataStorage
    _whale_file_lock = threading.Lock()
    
    def __init__(self, data_file: str = None):
        self.data_file = data_file or ScannerConfig.DATA_FILE
        self.price_tolerance = ScannerConfig.PRICE_TOLERANCE
        self.verbose_logs = ScannerConfig.VERBOSE_LOGS
    
    def load_existing_data(self) -> List[Dict]:
        """Загружаем существующие данные из файла"""
        if not os.path.exists(self.data_file):
            return []
        
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка чтения существующих данных: {e}")
            return []
    
    def save_all_data(self, all_data: List[Dict]):
        """Сохраняем все данные в файл"""
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Ошибка сохранения данных: {e}")
    
    def clear_data_file(self):
        """Очищаем файл с данными"""
        try:
            # Очищаем основной файл данных
            if os.path.exists(self.data_file):
                os.remove(self.data_file)
            
            # Очищаем файл со списком символов
            whale_file = ScannerConfig.WHALE_SYMBOLS_FILE
            if os.path.exists(whale_file):
                os.remove(whale_file)
            
            print("Старые данные очищены")
        except Exception as e:
            print(f"Ошибка очистки файла: {e}")
    
    def merge_orders_data(self, new_symbol_data: SymbolResult) -> SymbolResult:
        """Объединяем новые данные с существующими без потери истории"""
        existing_data = self.load_existing_data()
        current_time = datetime.now().isoformat()
        
        # Находим существующий символ
        existing_symbol_data = None
        for data in existing_data:
            if data['symbol'] == new_symbol_data.symbol:
                existing_symbol_data = data
                break
        
        if not existing_symbol_data:
            # Новый символ - помечаем все ордера как новые
            for order in new_symbol_data.orders:
                order.first_seen = current_time
                order.last_seen = current_time  
                order.is_persistent = False
                order.scan_count = 1
                order.lifetime_minutes = 0
            return new_symbol_data
        
        # Обрабатываем существующие и новые ордера
        merged_orders = []
        new_orders = new_symbol_data.orders
        existing_orders = [OrderData.from_dict(order_dict) 
                          for order_dict in existing_symbol_data.get('orders', [])]
        
        # Помечаем какие ордера найдены в новом скане
        found_existing_orders = set()
        persistent_orders_log = []  # Для логирования персистентных ордеров
        
        # Обрабатываем новые ордера
        for new_order in new_orders:
            matched_existing = None
            
            # Ищем соответствующий существующий ордер
            for i, existing_order in enumerate(existing_orders):
                if OrderKey.orders_are_same(new_order, existing_order, self.price_tolerance):
                    matched_existing = existing_order
                    found_existing_orders.add(i)
                    break
            
            if matched_existing:
                # Существующий ордер - обновляем
                updated_order = new_order
                updated_order.first_seen = matched_existing.first_seen or current_time
                updated_order.last_seen = current_time
                updated_order.is_persistent = True
                updated_order.scan_count = matched_existing.scan_count + 1
                
                # Вычисляем время жизни
                try:
                    first_time = datetime.fromisoformat(matched_existing.first_seen or current_time)
                    current_time_dt = datetime.fromisoformat(current_time)
                    lifetime_minutes = (current_time_dt - first_time).total_seconds() / 60
                    updated_order.lifetime_minutes = round(lifetime_minutes, 1)
                    
                    # Логирование персистентных ордеров
                    order_info = f"{updated_order.type} ${updated_order.usd_value:,.0f} @ {updated_order.price:.4f}"
                    persistent_orders_log.append(f"  🔄 {order_info} (живет {lifetime_minutes:.1f}мин, скан #{updated_order.scan_count})")
                    
                except:
                    updated_order.lifetime_minutes = 0
                
                merged_orders.append(updated_order)
            else:
                # Новый ордер
                new_order.first_seen = current_time
                new_order.last_seen = current_time
                new_order.is_persistent = False  
                new_order.scan_count = 1
                new_order.lifetime_minutes = 0
                merged_orders.append(new_order)
        
        # Логирование персистентных ордеров
        if persistent_orders_log:
            print(f"🔍 {new_symbol_data.symbol}: Найдены персистентные ордера:")
            for log_line in persistent_orders_log:
                print(log_line)
        
        # Логируем удаленные ордера (которые были, но исчезли)
        removed_orders = []
        for i, existing_order in enumerate(existing_orders):
            if i not in found_existing_orders:  # Ордер исчез
                removed_orders.append(existing_order)
        
        if removed_orders and self.verbose_logs:
            print(f"🗑️ {new_symbol_data.symbol}: Удалены исчезнувшие ордера:")
            for order in removed_orders:
                print(f"  ❌ {order.type} ${order.usd_value:,.0f} @ {order.price:.4f} (жил {order.lifetime_minutes:.1f}мин)")
        
        # Устанавливаем обновленные ордера (исчезнувшие ордера автоматически не включены)
        new_symbol_data.orders = merged_orders
        return new_symbol_data
    
    def update_symbol_data(self, updated_symbol_data: SymbolResult):
        """Обновляем данные конкретного символа в файле"""
        all_data = self.load_existing_data()
        
        # Находим и заменяем данные символа
        symbol_found = False
        for i, data in enumerate(all_data):
            if data['symbol'] == updated_symbol_data.symbol:
                all_data[i] = updated_symbol_data.to_dict()
                symbol_found = True
                break
        
        # Если символа не было, добавляем
        if not symbol_found:
            all_data.append(updated_symbol_data.to_dict())
        
        # Сохраняем
        try:
            self.save_all_data(all_data)
            
            # Компактное логирование обновлений
            new_orders = [o for o in updated_symbol_data.orders if not o.is_persistent]
            persistent_orders = [o for o in updated_symbol_data.orders if o.is_persistent]
            
            if new_orders or self.verbose_logs:
                status_parts = []
                if new_orders:
                    status_parts.append(f"{len(new_orders)} новых")
                if persistent_orders:
                    status_parts.append(f"{len(persistent_orders)} перс.")
                
                status = ", ".join(status_parts) if status_parts else "0 ордеров"
                symbol_log = f"✅ {updated_symbol_data.symbol}: {status}"
                
                # Только в вербозном режиме или если есть новые ордера
                if new_orders or self.verbose_logs:
                    print(symbol_log)
            
        except Exception as e:
            print(f"Ошибка сохранения: {e}")
    
    def remove_symbol_from_data(self, symbol: str):
        """Удаляем символ из данных (если больше нет больших ордеров)"""
        all_data = self.load_existing_data()
        original_count = len(all_data)
        all_data = [data for data in all_data if data['symbol'] != symbol]
        
        if len(all_data) < original_count:
            try:
                self.save_all_data(all_data)
                # Логирование убрано - оно теперь в save_symbol_data_persistent
                
                # СРАЗУ удаляем из списка китов (если вызов не из save_symbol_data_persistent)
                # Проверяем stack trace чтобы избежать двойного вызова
                import traceback
                stack = traceback.extract_stack()
                if not any('save_symbol_data_persistent' in str(frame) for frame in stack):
                    self.remove_symbol_from_whale_list(symbol)
                    
            except Exception as e:
                print(f"Ошибка удаления символа: {e}")
    
    def save_symbol_data_persistent(self, symbol_result: SymbolResult):
        """Сохраняем данные с сохранением истории (персистентный режим)"""
        if not symbol_result.orders:
            # Проверяем, были ли у этого символа ордера раньше
            existing_data = self.load_existing_data()
            existing_symbol = None
            for data in existing_data:
                if data['symbol'] == symbol_result.symbol:
                    existing_symbol = data
                    break
            
            if existing_symbol and existing_symbol.get('orders'):
                # У символа были ордера, но теперь их нет - логируем удаление
                if self.verbose_logs:
                    print(f"🗑️ {symbol_result.symbol}: Все ордера исчезли, удаляем символ")
                    for order_dict in existing_symbol['orders']:
                        order = OrderData.from_dict(order_dict)
                        print(f"  ❌ {order.type} ${order.usd_value:,.0f} @ {order.price:.4f} (жил {order.lifetime_minutes:.1f}мин)")
            
            # Удаляем символ из данных
            self.remove_symbol_from_data(symbol_result.symbol)
            
            # СРАЗУ удаляем из списка китов
            self.remove_symbol_from_whale_list(symbol_result.symbol)
            return
        
        # Объединяем с существующими данными
        merged_symbol_data = self.merge_orders_data(symbol_result)
        
        # Сохраняем обновленные данные
        self.update_symbol_data(merged_symbol_data)
        
        # Приоритет записи - определяем по вызову
        import traceback
        stack = [str(frame) for frame in traceback.extract_stack()]
        is_from_hot_pool = any('hot_pool_worker' in frame for frame in stack)
        
        # Добавляем в список китов
        self.add_symbol_to_whale_list(merged_symbol_data, force_write=is_from_hot_pool)
    
    def save_symbol_data_simple(self, symbol_result: SymbolResult):
        """Простое сохранение без персистентности (для обратной совместимости)"""
        if not symbol_result.orders:
            return
        
        # Читаем существующие данные или создаем новые
        all_data = self.load_existing_data()
        
        # Добавляем новые данные
        all_data.append(symbol_result.to_dict())
        
        try:
            self.save_all_data(all_data)
            print(f"Сохранено {len(symbol_result.orders)} ордеров для {symbol_result.symbol}")
            
        except Exception as e:
            print(f"Ошибка сохранения данных: {e}")
    
    def add_symbol_to_whale_list(self, symbol_result: SymbolResult, force_write: bool = False):
        """
        Добавляем/обновляем символ в списке китов
        force_write=True - приоритет записи (горячий пул)
        force_write=False - проверяем дубли (общий пул)
        """
        with self._whale_file_lock:
            try:
                whale_file = ScannerConfig.WHALE_SYMBOLS_FILE
                
                # Загружаем существующие данные
                whale_symbols = []
                if os.path.exists(whale_file):
                    try:
                        with open(whale_file, 'r', encoding='utf-8') as f:
                            content = f.read().strip()
                            if content:
                                whale_symbols = json.loads(content)
                    except (json.JSONDecodeError, Exception) as e:
                        print(f"⚠️ Поврежденный whale_symbols.json: {e}")
                        print("🔧 Создаем новый...")
                        whale_symbols = []
                
                # ПРОВЕРКА ДУБЛЕЙ для общего пула
                if not force_write:
                    # Проверяем, есть ли уже этот символ
                    for existing_symbol in whale_symbols:
                        if existing_symbol['symbol'] == symbol_result.symbol:
                            # print(f"⚠️ {symbol_result.symbol}: Уже в горячем пуле, пропускаем")
                            return  # ПРОПУСКАЕМ ДУБЛИ!
                
                # Считаем метрики
                total_volume = sum(order.usd_value for order in symbol_result.orders)
                largest_whale = max(order.usd_value for order in symbol_result.orders)
                longest_lifetime = max(order.lifetime_minutes for order in symbol_result.orders) if symbol_result.orders else 0
                
                new_symbol_data = {
                    "symbol": symbol_result.symbol,
                    "orders_count": len(symbol_result.orders),
                    "total_volume": round(total_volume, 2),
                    "largest_whale": round(largest_whale, 2),
                    "longest_order_lifetime": round(longest_lifetime, 1),
                    "last_updated": symbol_result.timestamp,
                    "current_price": symbol_result.current_price,
                    "volatility_1h": symbol_result.volatility_1h
                }
                
                # Обновляем или добавляем
                symbol_found = False
                for i, whale_symbol in enumerate(whale_symbols):
                    if whale_symbol['symbol'] == symbol_result.symbol:
                        whale_symbols[i] = new_symbol_data
                        symbol_found = True
                        break
                
                if not symbol_found:
                    whale_symbols.append(new_symbol_data)
                    pool_type = "🔥 ГОРЯЧИЙ" if force_write else "📊 ОБЩИЙ"
                    print(f"📋 {symbol_result.symbol}: Добавлен в киты {pool_type} (${total_volume:,.0f})")
                
                # Сортируем и сохраняем
                whale_symbols.sort(key=lambda x: x['total_volume'], reverse=True)
                
                # Атомарная запись
                temp_file = whale_file + ".tmp"
                with open(temp_file, 'w', encoding='utf-8') as f:
                    json.dump(whale_symbols, f, ensure_ascii=False, indent=2)
                
                # Атомарное перемещение
                if os.name == 'nt':  # Windows
                    if os.path.exists(whale_file):
                        os.remove(whale_file)
                    os.rename(temp_file, whale_file)
                else:  # Unix/Linux
                    os.rename(temp_file, whale_file)
                    
            except Exception as e:
                print(f"❌ Ошибка записи whale_symbols: {e}")
    
    def remove_symbol_from_whale_list(self, symbol: str):
        """Удаляем символ из списка китов THREAD-SAFE"""
        with self._whale_file_lock:
            try:
                whale_file = ScannerConfig.WHALE_SYMBOLS_FILE
                
                if not os.path.exists(whale_file):
                    return  # Файл не существует
                
                # Загружаем существующий список
                try:
                    with open(whale_file, 'r', encoding='utf-8') as f:
                        whale_symbols = json.load(f)
                except (json.JSONDecodeError, Exception) as e:
                    print(f"⚠️ Поврежденный whale_symbols.json при удалении: {e}")
                    return
                
                # Удаляем символ
                original_count = len(whale_symbols)
                whale_symbols = [ws for ws in whale_symbols if ws['symbol'] != symbol]
                
                if len(whale_symbols) < original_count:
                    print(f"🗑️ {symbol}: Удален из списка китов")
                    
                    # Атомарное сохранение
                    temp_file = whale_file + ".tmp"
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        json.dump(whale_symbols, f, ensure_ascii=False, indent=2)
                    
                    # Атомарное перемещение
                    if os.name == 'nt':  # Windows
                        if os.path.exists(whale_file):
                            os.remove(whale_file)
                        os.rename(temp_file, whale_file)
                    else:  # Unix/Linux
                        os.rename(temp_file, whale_file)
                        
            except Exception as e:
                print(f"❌ Ошибка удаления из whale_symbols: {e}")
