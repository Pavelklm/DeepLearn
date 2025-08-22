#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Персистентное хранение данных ордеров
"""

import json
import os
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
            if os.path.exists(self.data_file):
                os.remove(self.data_file)
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
        
        # НЕ добавляем ордера, которые исчезли (они автоматически удаляются)
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
                print(f"  Удален {symbol} (нет больших ордеров)")
            except Exception as e:
                print(f"Ошибка удаления символа: {e}")
    
    def save_symbol_data_persistent(self, symbol_result: SymbolResult):
        """Сохраняем данные с сохранением истории (персистентный режим)"""
        if not symbol_result.orders:
            # Даже если нет больших ордеров, нужно обновить существующие данные
            # (удалить ордера, которых больше нет)
            self.remove_symbol_from_data(symbol_result.symbol)
            return
        
        # Объединяем с существующими данными
        merged_symbol_data = self.merge_orders_data(symbol_result)
        
        # Сохраняем обновленные данные
        self.update_symbol_data(merged_symbol_data)
    
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
