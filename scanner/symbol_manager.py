#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Управление символами и их фильтрация
"""

from typing import List, Dict
from .api_client import BinanceAPIClient
from .config import ScannerConfig


class SymbolManager:
    """Менеджер для работы с торговыми символами"""
    
    def __init__(self, api_client: BinanceAPIClient):
        self.api_client = api_client
        self.excluded_symbols = ScannerConfig.EXCLUDED_SYMBOLS
        self.top_symbols_count = ScannerConfig.TOP_SYMBOLS_COUNT
        self.verbose_logs = ScannerConfig.VERBOSE_LOGS
    
    def get_active_symbols(self) -> List[str]:
        """Получаем список активных фьючерсных символов"""
        try:
            data = self.api_client.get_exchange_info()
            symbols = []
            
            for symbol_info in data['symbols']:
                symbol = symbol_info['symbol']
                # Только USDT пары в активном статусе
                if (symbol.endswith('USDT') and 
                    symbol_info['status'] == 'TRADING' and
                    symbol not in self.excluded_symbols):
                    symbols.append(symbol)
            
            print(f"Найдено {len(symbols)} активных символов для сканирования")
            return symbols 
            
        except Exception as e:
            print(f"Ошибка получения символов: {e}")
            return []
    
    def get_all_tickers_batch(self) -> Dict[str, Dict]:
        """Получаем 24hr статистику для ВСЕХ символов одним запросом"""
        try:
            tickers_list = self.api_client.get_all_tickers_24hr()
            tickers_dict = {ticker['symbol']: ticker for ticker in tickers_list}
            
            if self.verbose_logs:
                print(f"Получены ticker данные для {len(tickers_dict)} символов одним запросом")
            return tickers_dict
            
        except Exception as e:
            print(f"Ошибка получения batch ticker: {e}")
            return {}
    
    def filter_top_symbols_by_volume(self, symbols: List[str], all_tickers: Dict[str, Dict], 
                                   top_count: int = None) -> List[str]:
        """Фильтруем топ-N символов по объему торгов за 24ч"""
        top_count = top_count or self.top_symbols_count
        
        try:
            # Создаем список (символ, объем_торгов) для сортировки
            symbol_volumes = []
            for symbol in symbols:
                ticker_data = all_tickers.get(symbol)
                if ticker_data:
                    # Используем quoteVolume (общий объем в USDT за 24ч) как метрику капитализации
                    volume_24h = float(ticker_data.get('quoteVolume', 0))
                    symbol_volumes.append((symbol, volume_24h))
            
            # Сортируем по объему торгов (по убыванию) и берем топ-N
            symbol_volumes.sort(key=lambda x: x[1], reverse=True)
            top_symbols = [symbol for symbol, volume in symbol_volumes[:top_count]]
            
            if self.verbose_logs:
                print(f"Отфильтровано: {len(symbols)} → {len(top_symbols)} символов (топ-{top_count} по объему торгов)")
                
                # Показываем примеры топ-10 для информации
                if len(symbol_volumes) >= 10:
                    print("Топ-10 по объему торгов:")
                    for i, (symbol, volume) in enumerate(symbol_volumes[:10], 1):
                        volume_millions = volume / 1_000_000  # Конвертируем в миллионы USDT
                        print(f"  {i:2d}. {symbol:12s} - {volume_millions:8.1f}M USDT")
            
            return top_symbols
            
        except Exception as e:
            print(f"Ошибка фильтрации символов по объему: {e}")
            print("Используем все символы без фильтрации")
            return symbols
    
    def get_filtered_symbols(self) -> tuple[List[str], Dict[str, Dict]]:
        """Получаем отфильтрованный список символов и их ticker данные"""
        # Получаем все активные символы
        symbols = self.get_active_symbols()
        if not symbols:
            return [], {}
        
        # Получаем ticker данные для всех символов
        if self.verbose_logs:
            print("Получаем ВСЕ ticker данные одним batch запросом...")
        all_tickers = self.get_all_tickers_batch()
        if not all_tickers:
            print("Ошибка получения batch ticker!")
            return [], {}
        
        # Фильтруем топ символы по объему торгов
        if self.verbose_logs:
            print(f"Фильтруем топ-{self.top_symbols_count} символов по объему торгов...")
        filtered_symbols = self.filter_top_symbols_by_volume(symbols, all_tickers)
        
        return filtered_symbols, all_tickers
