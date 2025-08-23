#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Анализ ордеров и поиск больших заявок
"""

from typing import List, Dict
from datetime import datetime
try:
    from data_models import OrderData, SymbolData, SymbolMetrics
    from config import ScannerConfig
except ImportError:
    from .data_models import OrderData, SymbolData, SymbolMetrics
    from .config import ScannerConfig


class OrderAnalyzer:
    """Анализатор ордеров для поиска больших заявок"""
    
    def __init__(self):
        self.whale_multiplier = ScannerConfig.WHALE_MULTIPLIER
        self.max_orders_per_side = ScannerConfig.MAX_ORDERS_PER_SIDE
        self.volatility_multiplier = ScannerConfig.VOLATILITY_MULTIPLIER
    
    def find_big_orders(self, symbol: str, order_book: Dict, symbol_data: SymbolData, 
                       symbol_metrics: SymbolMetrics) -> List[OrderData]:
        """Находим большие ордера в стакане (максимум 3 с каждой стороны)"""
        big_orders = []
        
        if not order_book or not symbol_data:
            return big_orders
        
        current_price = symbol_data.current_price
        
        # Динамический радиус на основе волатильности
        dynamic_distance = symbol_metrics.volatility_1h * self.volatility_multiplier
        
        # Рассчитываем адаптивный порог
        avg_order_size = self._calculate_average_order_size(order_book)
        adaptive_threshold = avg_order_size * self.whale_multiplier
        
        # Временные списки для сортировки
        ask_orders = []
        bid_orders = []
        
        # Обрабатываем аски (продажи)
        ask_orders = self._process_asks(order_book, current_price, adaptive_threshold, avg_order_size, symbol, dynamic_distance)
        
        # Обрабатываем биды (покупки)
        bid_orders = self._process_bids(order_book, current_price, adaptive_threshold, avg_order_size, symbol, dynamic_distance)
        
        # Сортируем и берем топ-N самых больших ордеров с каждой стороны
        # ASK: сортируем по размеру (самые большие сначала)
        ask_orders.sort(key=lambda x: x.usd_value, reverse=True)
        for i, order in enumerate(ask_orders[:self.max_orders_per_side]):
            order.rank_in_side = i + 1
            big_orders.append(order)
        
        # BID: сортируем по размеру (самые большие сначала) 
        bid_orders.sort(key=lambda x: x.usd_value, reverse=True)
        for i, order in enumerate(bid_orders[:self.max_orders_per_side]):
            order.rank_in_side = i + 1
            big_orders.append(order)
        
        return big_orders
    
    def _calculate_average_order_size(self, order_book: Dict) -> float:
        """Рассчитываем средний размер ордера в стакане"""
        all_order_sizes = []
        
        for ask in order_book.get('asks', []):
            all_order_sizes.append(float(ask[0]) * float(ask[1]))
        for bid in order_book.get('bids', []):
            all_order_sizes.append(float(bid[0]) * float(bid[1]))
        
        return sum(all_order_sizes) / len(all_order_sizes) if all_order_sizes else 1
    
    def _process_asks(self, order_book: Dict, current_price: float, adaptive_threshold: float,
                     avg_order_size: float, symbol: str, dynamic_distance: float) -> List[OrderData]:
        """Обрабатываем ордера на продажу (аски)"""
        ask_orders = []
        
        for ask in order_book.get('asks', []):
            price = float(ask[0])
            quantity = float(ask[1])
            usd_value = price * quantity
            
            if usd_value >= adaptive_threshold:
                distance_percent = ((price - current_price) / current_price) * 100
                
                # Пропускаем ордера дальше динамического радиуса
                if abs(distance_percent) > dynamic_distance:
                    continue
                
                # Количество ордеров в радиусе ±0.1% от цены
                orders_around_count = self._count_orders_around_price(
                    order_book.get('asks', []), price)
                
                order_data = OrderData(
                    symbol=symbol,
                    type='ASK',
                    price=price,
                    quantity=quantity,
                    usd_value=usd_value,
                    distance_percent=distance_percent,
                    size_vs_average=usd_value / avg_order_size if avg_order_size > 0 else 1,
                    orders_around_price=orders_around_count,
                    rank_in_side=0,  # Будет установлен позже
                    timestamp=datetime.now().isoformat(),
                    average_order_size=avg_order_size
                )
                ask_orders.append(order_data)
        
        return ask_orders
    
    def _process_bids(self, order_book: Dict, current_price: float, adaptive_threshold: float,
                     avg_order_size: float, symbol: str, dynamic_distance: float) -> List[OrderData]:
        """Обрабатываем ордера на покупку (биды)"""
        bid_orders = []
        
        for bid in order_book.get('bids', []):
            price = float(bid[0])
            quantity = float(bid[1])
            usd_value = price * quantity
            
            if usd_value >= adaptive_threshold:
                distance_percent = ((price - current_price) / current_price) * 100
                
                # Пропускаем ордера дальше динамического радиуса
                if abs(distance_percent) > dynamic_distance:
                    continue
                
                # Количество ордеров в радиусе ±0.1% от цены
                orders_around_count = self._count_orders_around_price(
                    order_book.get('bids', []), price)
                
                order_data = OrderData(
                    symbol=symbol,
                    type='BID',
                    price=price,
                    quantity=quantity,
                    usd_value=usd_value,
                    distance_percent=distance_percent,
                    size_vs_average=usd_value / avg_order_size if avg_order_size > 0 else 1,
                    orders_around_price=orders_around_count,
                    rank_in_side=0,  # Будет установлен позже
                    timestamp=datetime.now().isoformat(),
                    average_order_size=avg_order_size
                )
                bid_orders.append(order_data)
        
        return bid_orders
    
    def _count_orders_around_price(self, orders: List, target_price: float) -> int:
        """Подсчитываем количество ордеров в радиусе ±0.1% от цены"""
        price_range_low = target_price * 0.999
        price_range_high = target_price * 1.001
        count = 0
        
        for order in orders:
            order_price = float(order[0])
            if price_range_low <= order_price <= price_range_high:
                count += 1
        
        return count
