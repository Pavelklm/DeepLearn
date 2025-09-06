# Файл: trading/strategies/ema_crossover_strategy.py

import pandas as pd
from strategies.base_strategy import BaseStrategy

class Strategy(BaseStrategy):
    """
    Простая стратегия на пересечении двух EMA.
    Теперь она принимает параметры динамически.
    """
    # ИЗМЕНЕНИЕ: Принимаем параметры в конструкторе
    def __init__(self, fast_ema_period=7, slow_ema_period=25, tp_multiplier=1.197):
        self._name = f"EMA Crossover ({fast_ema_period}/{slow_ema_period})"
        self.fast_ema_period = fast_ema_period
        self.slow_ema_period = slow_ema_period
        self.tp_multiplier = tp_multiplier # Добавляем настраиваемый тейк-профит

    @property
    def name(self) -> str:
        return self._name

    def analyze(self, historical_data: pd.DataFrame) -> dict:
        """
        Анализирует исторические данные и возвращает решение.
        """
        # Условие для достаточного количества данных
        if len(historical_data) < self.slow_ema_period + 2:
            return {'signal': 'hold'}

        ema_fast = historical_data['Close'].ewm(span=self.fast_ema_period, adjust=False).mean()
        ema_slow = historical_data['Close'].ewm(span=self.slow_ema_period, adjust=False).mean()

        prev_fast = ema_fast.iloc[-2].item()
        curr_fast = ema_fast.iloc[-1].item()
        prev_slow = ema_slow.iloc[-2].item()
        curr_slow = ema_slow.iloc[-1].item()

        if prev_fast <= prev_slow and curr_fast > curr_slow:
            current_price = historical_data['Close'].iloc[-1].item()
            return {
                'signal': 'buy',
                'entry_price': current_price,
                # ИЗМЕНЕНИЕ: Используем настраиваемый множитель для TP
                'target_tp_price': current_price * self.tp_multiplier
            }

        return {'signal': 'hold'}