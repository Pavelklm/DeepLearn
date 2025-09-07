# Файл: trading/strategies/rsi_sma_strategy.py

import pandas as pd
# Убираем импорт pandas_ta
from strategies.base_strategy import BaseStrategy

class Strategy(BaseStrategy):
    """
    Стратегия, использующая RSI для входа и SMA как фильтр тренда.
    Версия, которая вычисляет индикаторы напрямую через pandas.
    """
    def __init__(self, rsi_period=14, sma_period=50, oversold_level=30, tp_multiplier=1.05, overbought_level=70):
        self._name = f"RSI({rsi_period})_SMA({sma_period})"
        self.rsi_period = int(rsi_period)
        self.sma_period = int(sma_period)
        self.oversold_level = int(oversold_level)
        self.overbought_level = int(overbought_level)
        self.tp_multiplier = tp_multiplier
        if not isinstance(self.rsi_period, int) or not isinstance(self.sma_period, int):
            raise TypeError("Периоды индикаторов должны быть целыми числами.")

    @property
    def name(self) -> str:
        return self._name

    def _calculate_rsi(self, data: pd.Series, period: int) -> pd.Series:
        """Вычисляет RSI с помощью pandas."""
        delta = data.diff()
        
        up = delta.clip(lower=0)
        down = -1 * delta.clip(upper=0)
        
        # Используем экспоненциальное среднее для более точного RSI
        ema_up = up.ewm(com=period - 1, adjust=False).mean()
        ema_down = down.ewm(com=period - 1, adjust=False).mean()
        
        rs = ema_up / ema_down
        rsi = 100 - (100 / (1 + rs))
        return rsi

    def analyze(self, historical_data: pd.DataFrame) -> dict:
        # Проверка на достаточность данных для самого длинного периода
        if len(historical_data) < max(self.rsi_period, self.sma_period) + 2:
            return {'signal': 'hold'}

        # --- Вычисляем индикаторы ---
        rsi = self._calculate_rsi(historical_data['Close'], self.rsi_period)
        sma = historical_data['Close'].rolling(window=self.sma_period).mean()
        
        # --- ГАРАНТИРОВАННОЕ РЕШЕНИЕ ---
        # Проверяем самое последнее значение индикатора. Если оно NaN, значит,
        # расчеты еще не завершены, и мы должны ждать.
        # Это возвращает ОДНО значение True или False.
        if pd.isna(rsi.values[-1]) or pd.isna(sma.values[-1]):
            return {'signal': 'hold'}

        # Получаем последние значения для анализа
        current_price = historical_data['Close'].values[-1]
        prev_rsi = rsi.values[-2]
        curr_rsi = rsi.values[-1]
        curr_sma = sma.values[-1]
        
        # Условие для входа (более агрессивное):
        # 1. Цена выше медленной SMA (фильтр восходящего тренда).
        # 2. RSI ниже уровня перепроданности (не требуем пересечения).
        if current_price > curr_sma and curr_rsi <= self.oversold_level:
            return {
            'signal': 'buy',
            'entry_price': float(current_price),
            'target_tp_price': float(current_price * self.tp_multiplier)
            }

        return {'signal': 'hold'}

    def check_exit_signal(self, trade: dict) -> bool:
        """
        Простая логика выхода: пока отключена для тестирования входов
        """
        return False  # Пока отключаем выход для тестирования входов