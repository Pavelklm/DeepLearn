#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Расчет метрик и аналитики символов
"""

from typing import Dict, List

try:
    from api_client import BinanceAPIClient
    from data_models import SymbolData, SymbolMetrics
    from config import ScannerConfig
except ImportError:
    from .api_client import BinanceAPIClient
    from .data_models import SymbolData, SymbolMetrics
    from .config import ScannerConfig


class MetricsCalculator:
    """Калькулятор метрик для символов"""
    
    def __init__(self, api_client: BinanceAPIClient):
        self.api_client = api_client
    
    def get_symbol_data(self, symbol: str, ticker_data: Dict = None) -> SymbolData:
        """Получаем полные данные символа: цену, статистику 24ч, свечи для волатильности"""
        try:
            # Используем переданные ticker_data (batch) или делаем fallback запрос
            if ticker_data:
                # BATCH режим: данные уже получены
                current_price = float(ticker_data['lastPrice'])
            else:
                # FALLBACK режим: отдельный запрос (если batch не сработал)
                print(f"  FALLBACK: отдельный ticker запрос для {symbol}")
                ticker_data = self.api_client.get_ticker_24hr(symbol)
                current_price = float(ticker_data['lastPrice'])
            
            # Свечи за последний 1 час для расчета волатильности (оптимизировано)
            klines_data = self.api_client.get_klines(symbol, "5m", 12)
            
            return SymbolData(
                current_price=current_price,
                ticker_data=ticker_data,
                klines_data=klines_data
            )
            
        except Exception as e:
            print(f"Ошибка получения данных для {symbol}: {e}")
            return None
    
    def calculate_symbol_metrics(self, symbol_data: SymbolData, order_book: Dict) -> SymbolMetrics:
        """Рассчитываем метрики символа"""
        if not symbol_data or not order_book:
            return SymbolMetrics()
        
        current_price = symbol_data.current_price
        ticker_data = symbol_data.ticker_data
        klines_data = symbol_data.klines_data
        
        # Волатильность за 1 час (средний % изменения за 12 последних 5-минутных свечей)
        volatility_1h = self._calculate_volatility_1h(klines_data)
        
        # Отношение текущего объема к среднему
        volume_ratio = self._calculate_volume_ratio(ticker_data, current_price)
        
        # Изменение цены за 5 минут
        price_movement_5min = self._calculate_price_movement_5min(klines_data, current_price)
        
        # Находится ли цена на круглом уровне
        is_round_level = self._is_round_level(current_price)
        
        return SymbolMetrics(
            volatility_1h=volatility_1h,
            volume_ratio=volume_ratio,
            price_movement_5min=price_movement_5min,
            is_round_level=is_round_level
        )
    
    def _calculate_volatility_1h(self, klines_data: List) -> float:
        """Рассчитываем волатильность за 1 час"""
        if len(klines_data) < 12:
            return 0
        
        hour_changes = []
        for i in range(-12, 0):  # Последние 12 свечей (1 час)
            open_price = float(klines_data[i][1])
            close_price = float(klines_data[i][4])
            if open_price > 0:
                change_percent = abs((close_price - open_price) / open_price * 100)
                hour_changes.append(change_percent)
        
        return sum(hour_changes) / len(hour_changes) if hour_changes else 0
    
    def _calculate_volume_ratio(self, ticker_data: Dict, current_price: float) -> float:
        """Рассчитываем отношение текущего объема к среднему"""
        current_volume = float(ticker_data.get('volume', 0))
        avg_volume = float(ticker_data.get('quoteVolume', 1)) / current_price if current_price > 0 else 1
        return current_volume / avg_volume if avg_volume > 0 else 1
    
    def _calculate_price_movement_5min(self, klines_data: List, current_price: float) -> float:
        """Рассчитываем изменение цены за 5 минут"""
        if len(klines_data) < 1:
            return 0
        
        price_5min_ago = float(klines_data[-1][1])  # Open price последней свечи
        if price_5min_ago > 0:
            return (current_price - price_5min_ago) / price_5min_ago * 100
        return 0
    
    def _is_round_level(self, current_price: float) -> bool:
        """Проверяем, находится ли цена на круглом уровне"""
        price_str = f"{current_price:.10f}".rstrip('0').rstrip('.')
        return (
            current_price % 100 == 0 or 
            current_price % 50 == 0 or 
            current_price % 10 == 0 or
            price_str.endswith('0') or
            price_str.endswith('00') or
            price_str.endswith('5')
        )
