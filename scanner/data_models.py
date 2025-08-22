#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Модели данных для сканера больших ордеров
"""

from typing import List, Dict, Optional
from datetime import datetime
from dataclasses import dataclass, asdict


@dataclass
class OrderData:
    """Модель данных ордера"""
    symbol: str
    type: str  # 'ASK' или 'BID'
    price: float
    quantity: float
    usd_value: float
    distance_percent: float
    size_vs_average: float
    orders_around_price: int
    rank_in_side: int
    timestamp: str
    
    # Поля для персистентности
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    is_persistent: bool = False
    scan_count: int = 1
    lifetime_minutes: float = 0
    
    def to_dict(self) -> Dict:
        """Конвертируем в словарь"""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'OrderData':
        """Создаем объект из словаря"""
        return cls(**data)


@dataclass
class SymbolMetrics:
    """Метрики символа"""
    volatility_1h: float = 0
    volume_ratio: float = 1
    price_movement_5min: float = 0
    is_round_level: bool = False
    
    def to_dict(self) -> Dict:
        """Конвертируем в словарь"""
        return asdict(self)


@dataclass
class SymbolData:
    """Данные символа"""
    current_price: float
    ticker_data: Dict
    klines_data: List
    
    def to_dict(self) -> Dict:
        """Конвертируем в словарь"""
        return asdict(self)


@dataclass
class SymbolResult:
    """Результат обработки символа"""
    symbol: str
    timestamp: str
    current_price: float
    volatility_1h: float
    volume_ratio: float
    price_movement_5min: float
    is_round_level: bool
    orders_count: int
    orders: List[OrderData]
    
    def to_dict(self) -> Dict:
        """Конвертируем в словарь"""
        result = asdict(self)
        # Конвертируем ордера в словари
        result['orders'] = [order.to_dict() if isinstance(order, OrderData) else order for order in self.orders]
        return result
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SymbolResult':
        """Создаем объект из словаря"""
        # Конвертируем ордера из словарей в объекты
        orders = []
        for order_data in data.get('orders', []):
            if isinstance(order_data, dict):
                orders.append(OrderData.from_dict(order_data))
            else:
                orders.append(order_data)
        
        data['orders'] = orders
        return cls(**data)


class OrderKey:
    """Утилиты для работы с ключами ордеров"""
    
    @staticmethod
    def create_order_key(order: OrderData) -> str:
        """Создаем уникальный ключ для ордера"""
        return f"{order.symbol}-{order.type}-{order.price:.8f}-{order.quantity:.8f}"
    
    @staticmethod
    def orders_are_same(order1: OrderData, order2: OrderData, tolerance: float = 0.0001) -> bool:
        """Проверяем, один ли это ордер (с учетом небольших изменений)"""
        if order1.symbol != order2.symbol or order1.type != order2.type:
            return False
        
        # Проверяем разницу в цене и количестве (в процентах)
        price_diff = abs(order1.price - order2.price) / order1.price if order1.price > 0 else 1
        quantity_diff = abs(order1.quantity - order2.quantity) / order1.quantity if order1.quantity > 0 else 1
        
        # Ордеры считаются одинаковыми, если разница меньше допустимой
        return price_diff <= tolerance and quantity_diff <= tolerance
