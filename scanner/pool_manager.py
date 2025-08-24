#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Менеджер пулов для многоуровневого сканирования
"""

import json
import os
from typing import Dict, List, Set, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum

try:
    from config import ScannerConfig
except ImportError:
    from .config import ScannerConfig


class PoolType(Enum):
    """Типы пулов сканирования"""
    HOT = "hot"           # Горячий пул - активные киты
    WATCH = "watch"       # Пул наблюдения - недавно потерянные
    GENERAL = "general"   # Общий пул - все остальные


@dataclass
class WatchSymbol:
    """Символ в пуле наблюдения"""
    symbol: str
    added_time: str  # Когда добавлен в наблюдение
    scan_count: int = 0  # Количество сканов в пуле наблюдения
    last_scan_time: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'WatchSymbol':
        return cls(**data)


class PoolManager:
    """Менеджер пулов для многоуровневого сканирования"""
    
    def __init__(self):
        self.whale_file = ScannerConfig.WHALE_SYMBOLS_FILE
        self.watch_symbols: Dict[str, WatchSymbol] = {}  # В памяти
        self._cached_hot_symbols: Set[str] = set()
        self._last_hot_update: Optional[datetime] = None
        
    def get_hot_pool_symbols(self, force_refresh: bool = False) -> Set[str]:
        """Получаем символы из горячего пула (whale_symbols.json)"""
        try:
            # Кэшируем на короткое время для производительности
            now = datetime.now()
            if (not force_refresh and self._last_hot_update and 
                (now - self._last_hot_update).total_seconds() < 5):
                return self._cached_hot_symbols
            
            if not os.path.exists(self.whale_file):
                self._cached_hot_symbols = set()
                self._last_hot_update = now
                return self._cached_hot_symbols
            
            with open(self.whale_file, 'r', encoding='utf-8') as f:
                whale_data = json.load(f)
            
            self._cached_hot_symbols = {item['symbol'] for item in whale_data}
            self._last_hot_update = now
            return self._cached_hot_symbols
            
        except Exception as e:
            print(f"Ошибка чтения горячего пула: {e}")
            return set()
    
    def get_watch_pool_symbols(self) -> Set[str]:
        """Получаем символы из пула наблюдения"""
        return set(self.watch_symbols.keys())
    
    def add_to_watch_pool(self, symbol: str):
        """Добавляем символ в пул наблюдения"""
        if symbol not in self.watch_symbols:
            self.watch_symbols[symbol] = WatchSymbol(
                symbol=symbol,
                added_time=datetime.now().isoformat(),
                scan_count=0
            )
            print(f"📋 {symbol}: Добавлен в пул наблюдения")
    
    def increment_watch_scan(self, symbol: str) -> bool:
        """
        Увеличиваем счетчик сканов для символа в наблюдении
        Возвращает True, если символ нужно переместить в общий пул
        """
        if symbol not in self.watch_symbols:
            return False
        
        watch_symbol = self.watch_symbols[symbol]
        watch_symbol.scan_count += 1
        watch_symbol.last_scan_time = datetime.now().isoformat()
        
        # Проверяем, не превысил ли лимит сканов
        if watch_symbol.scan_count >= ScannerConfig.WATCH_MAX_SCANS:
            print(f"🔄 {symbol}: Переводим в общий пул после {watch_symbol.scan_count} сканов")
            del self.watch_symbols[symbol]
            return True
        
        return False
    
    def remove_from_watch_pool(self, symbol: str):
        """Удаляем символ из пула наблюдения (например, если вернулся в горячий)"""
        if symbol in self.watch_symbols:
            print(f"🔥 {symbol}: Вернулся в горячий пул из наблюдения")
            del self.watch_symbols[symbol]
    
    def check_hot_pool_changes(self) -> List[str]:
        """
        Проверяем изменения в горячем пуле и возвращаем символы, 
        которые нужно добавить в пул наблюдения
        """
        # ПРИНУДИТЕЛЬНО перечитываем файл
        current_hot = self.get_hot_pool_symbols(force_refresh=True)
        previous_hot = getattr(self, '_previous_hot_symbols', set())
        
        # Символы, которые исчезли из горячего пула
        lost_symbols = previous_hot - current_hot
        
        # Символы, которые вернулись в горячий пул из наблюдения
        returned_symbols = current_hot & set(self.watch_symbols.keys())
        
        # Удаляем вернувшиеся символы из пула наблюдения
        for symbol in returned_symbols:
            self.remove_from_watch_pool(symbol)
        
        # Логирование изменений
        if lost_symbols:
            print(f"📋 Исчезли из горячего пула: {list(lost_symbols)}")
        if returned_symbols:
            print(f"🔥 Вернулись в горячий пул: {list(returned_symbols)}")
        
        # Сохраняем текущее состояние для следующей проверки
        self._previous_hot_symbols = current_hot.copy()
        
        return list(lost_symbols)
    
    def get_general_pool_symbols(self, all_symbols: List[str]) -> List[str]:
        """
        Получаем символы для общего пула (исключая горячий и наблюдение)
        """
        hot_symbols = self.get_hot_pool_symbols()
        watch_symbols = self.get_watch_pool_symbols()
        excluded_symbols = hot_symbols | watch_symbols
        
        return [symbol for symbol in all_symbols if symbol not in excluded_symbols]
    
    def get_pool_type(self, symbol: str) -> PoolType:
        """Определяем, к какому пулу относится символ"""
        if symbol in self.get_hot_pool_symbols():
            return PoolType.HOT
        elif symbol in self.get_watch_pool_symbols():
            return PoolType.WATCH
        else:
            return PoolType.GENERAL
    
    def get_pools_status(self) -> Dict[str, int]:
        """Получаем статистику пулов"""
        return {
            "hot_pool": len(self.get_hot_pool_symbols()),
            "watch_pool": len(self.get_watch_pool_symbols()),
            "watch_symbols_details": [
                f"{ws.symbol}({ws.scan_count}/{ScannerConfig.WATCH_MAX_SCANS})"
                for ws in self.watch_symbols.values()
            ]
        }
    
    def cleanup_expired_watch_symbols(self):
        """Очищаем устаревшие символы из пула наблюдения (безопасность)"""
        now = datetime.now()
        expired_symbols = []
        
        for symbol, watch_symbol in self.watch_symbols.items():
            try:
                added_time = datetime.fromisoformat(watch_symbol.added_time)
                # Если символ в наблюдении больше часа - что-то не так
                if (now - added_time).total_seconds() > 3600:
                    expired_symbols.append(symbol)
            except:
                expired_symbols.append(symbol)  # Неверный формат времени
        
        for symbol in expired_symbols:
            print(f"🗑️ {symbol}: Удален из наблюдения (истек срок)")
            del self.watch_symbols[symbol]
