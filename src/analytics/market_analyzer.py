"""
Анализ рынка - определение условий и трендов
"""

from typing import Dict, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
import statistics
import asyncio

from src.exchanges.base_exchange import BaseExchange
from src.utils.logger import get_component_logger

logger = get_component_logger("market_analyzer")


class MarketAnalyzer:
    """Анализатор рыночных условий"""
    
    def __init__(self, exchange: BaseExchange):
        self.exchange = exchange
        self.logger = logger
        
        # Кэш рыночных данных
        self._volatility_cache: Dict[str, Dict] = {}
        self._market_state_cache: Optional[Dict] = None
        self._cache_ttl = 300  # 5 минут
        self._last_market_update = None
    
    async def get_market_volatility(self, timeframe: str = "1h") -> float:
        """
        Получить общую волатильность рынка
        
        Args:
            timeframe: Временной интервал (1h, 4h, 24h)
            
        Returns:
            Средняя волатильность топ-50 монет
        """
        try:
            # Получаем топ-50 символов по объему
            top_symbols = await self.exchange.get_top_volume_symbols(50)
            if not top_symbols:
                return 0.0
            
            volatilities = []
            
            # Получаем волатильность для каждого символа
            for symbol in top_symbols[:20]:  # Берем первые 20 для скорости
                try:
                    vol_data = await self.exchange.get_volatility_data(symbol, timeframe)
                    if vol_data and "volatility" in vol_data:
                        volatilities.append(vol_data["volatility"])
                        
                    await asyncio.sleep(0.1)  # Защита от лимитов API
                    
                except Exception as e:
                    self.logger.debug(f"Ошибка получения волатильности для {symbol}: {e}")
                    continue
            
            if not volatilities:
                return 0.0
            
            # Возвращаем медианную волатильность (более устойчивая метрика)
            market_vol = statistics.median(volatilities)
            
            self.logger.debug(f"Рыночная волатильность ({timeframe}): {market_vol:.4f}")
            return market_vol
            
        except Exception as e:
            self.logger.error(f"Ошибка расчета рыночной волатильности: {e}")
            return 0.0
    
    async def get_symbol_volatility(self, symbol: str, timeframe: str = "1h") -> Dict:
        """
        Получить волатильность конкретного символа с кэшированием
        
        Args:
            symbol: Торговая пара
            timeframe: Временной интервал
            
        Returns:
            Словарь с данными волатильности
        """
        cache_key = f"{symbol}_{timeframe}"
        now = datetime.now(timezone.utc)
        
        # Проверяем кэш
        if cache_key in self._volatility_cache:
            cached_data = self._volatility_cache[cache_key]
            cache_time = cached_data.get("timestamp")
            if cache_time and (now - cache_time).seconds < self._cache_ttl:
                return cached_data["data"]
        
        try:
            # Получаем новые данные
            vol_data = await self.exchange.get_volatility_data(symbol, timeframe)
            if not vol_data:
                vol_data = {"volatility": 0.0, "price_change": 0.0}
            
            # Кэшируем результат
            self._volatility_cache[cache_key] = {
                "data": vol_data,
                "timestamp": now
            }
            
            return vol_data
            
        except Exception as e:
            self.logger.error(f"Ошибка получения волатильности {symbol}: {e}")
            return {"volatility": 0.0, "price_change": 0.0}
    
    async def get_market_temperature(self) -> str:
        """
        Определить "температуру" рынка
        
        Returns:
            "cold", "warm", "hot", "extreme"
        """
        try:
            market_vol = await self.get_market_volatility("1h")
            
            if market_vol < 0.01:
                return "cold"
            elif market_vol < 0.03:
                return "warm"  
            elif market_vol < 0.06:
                return "hot"
            else:
                return "extreme"
                
        except Exception as e:
            self.logger.error(f"Ошибка определения температуры рынка: {e}")
            return "warm"  # Безопасное значение по умолчанию
    
    async def analyze_volume_spike(self, symbol: str) -> Dict:
        """
        Анализ всплеска объема для символа
        
        Args:
            symbol: Торговая пара
            
        Returns:
            Данные об аномалиях объема
        """
        try:
            # Получаем данные 24h статистики
            ticker_24h = await self.exchange.get_24h_ticker(symbol)
            if not ticker_24h:
                return {"spike_factor": 1.0, "is_spike": False}
            
            current_volume = float(ticker_24h.get("volume", 0))
            quote_volume = float(ticker_24h.get("quoteVolume", 0))
            
            # Простая эвристика: сравниваем с медианным объемом топ-100
            try:
                top_symbols = await self.exchange.get_top_volume_symbols(100)
                if symbol in top_symbols:
                    symbol_rank = top_symbols.index(symbol) + 1
                    
                    # Ожидаемый объем на основе ранга
                    expected_rank_volume = self._estimate_volume_by_rank(symbol_rank)
                    spike_factor = quote_volume / expected_rank_volume if expected_rank_volume > 0 else 1.0
                else:
                    spike_factor = 1.0
            except Exception:
                spike_factor = 1.0
            
            is_spike = spike_factor > 2.0  # Всплеск если объем в 2+ раза выше ожидаемого
            
            return {
                "spike_factor": spike_factor,
                "is_spike": is_spike,
                "current_volume": current_volume,
                "quote_volume": quote_volume
            }
            
        except Exception as e:
            self.logger.error(f"Ошибка анализа всплеска объема для {symbol}: {e}")
            return {"spike_factor": 1.0, "is_spike": False}
    
    def _estimate_volume_by_rank(self, rank: int) -> float:
        """Оценка объема по рангу (степенной закон)"""
        if rank <= 0:
            return 0.0
        
        # Простая модель: объем убывает пропорционально 1/rank^0.8
        base_volume = 10000000  # $10M для топ-1
        return base_volume / (rank ** 0.8)
    
    async def get_time_of_day_factor(self) -> float:
        """
        Получить модификатор активности в зависимости от времени суток
        
        Returns:
            Коэффициент активности (0.5 - 1.2)
        """
        now_utc = datetime.now(timezone.utc)
        hour = now_utc.hour
        
        # Азиатская сессия (00-08 UTC) - повышенная активность
        if 0 <= hour < 8:
            return 1.2
        # Европейская сессия (08-16 UTC) - нормальная активность
        elif 8 <= hour < 16:
            return 1.0
        # Американская сессия (16-24 UTC) - слегка повышенная
        else:
            return 1.1
    
    async def get_day_of_week_factor(self) -> float:
        """
        Получить модификатор активности в зависимости от дня недели
        
        Returns:
            Коэффициент активности (0.7 - 1.1)
        """
        now_utc = datetime.now(timezone.utc)
        weekday = now_utc.weekday()  # 0=понедельник, 6=воскресенье
        
        factors = {
            0: 1.1,  # Понедельник - начало недели
            1: 1.0,  # Вторник - обычный день
            2: 1.0,  # Среда - обычный день  
            3: 1.0,  # Четверг - обычный день
            4: 0.9,  # Пятница - конец недели
            5: 0.7,  # Суббота - выходной
            6: 0.8   # Воскресенье - выходной
        }
        
        return factors.get(weekday, 1.0)
    
    async def get_market_state(self) -> Dict:
        """
        Получить общее состояние рынка
        
        Returns:
            Полная сводка рыночных условий
        """
        now = datetime.now(timezone.utc)
        
        # Проверяем кэш общего состояния рынка
        if (self._market_state_cache and self._last_market_update and 
            (now - self._last_market_update).seconds < self._cache_ttl):
            return self._market_state_cache
        
        try:
            # Собираем все метрики
            market_vol = await self.get_market_volatility("1h")
            market_temp = await self.get_market_temperature()
            time_factor = await self.get_time_of_day_factor()
            day_factor = await self.get_day_of_week_factor()
            
            state = {
                "timestamp": now.isoformat(),
                "volatility_1h": market_vol,
                "market_temperature": market_temp,
                "time_of_day_factor": time_factor,
                "day_of_week_factor": day_factor,
                "combined_activity_factor": time_factor * day_factor,
                "is_high_volatility": market_vol > 0.05,
                "is_weekend": now.weekday() >= 5
            }
            
            # Кэшируем состояние
            self._market_state_cache = state
            self._last_market_update = now
            
            self.logger.debug(f"Состояние рынка обновлено: {market_temp}, волатильность: {market_vol:.4f}")
            return state
            
        except Exception as e:
            self.logger.error(f"Ошибка получения состояния рынка: {e}")
            
            # Возвращаем безопасные значения по умолчанию
            return {
                "timestamp": now.isoformat(),
                "volatility_1h": 0.02,
                "market_temperature": "warm",
                "time_of_day_factor": 1.0,
                "day_of_week_factor": 1.0,
                "combined_activity_factor": 1.0,
                "is_high_volatility": False,
                "is_weekend": now.weekday() >= 5
            }
    
    def clear_cache(self):
        """Очистка всех кэшей"""
        self._volatility_cache.clear()
        self._market_state_cache = None
        self._last_market_update = None
        self.logger.debug("Кэши анализатора рынка очищены")
