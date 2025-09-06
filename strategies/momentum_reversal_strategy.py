# Файл: strategies/momentum_reversal_strategy.py

import pandas as pd
from strategies.base_strategy import BaseStrategy

class Strategy(BaseStrategy):
    """
    Стратегия Momentum Reversal для бэктеста и оптимизации.
    Все параметры передаются напрямую в конструктор.
    """

    def __init__(self,
                 momentum_period: int = 3,
                 sma_trend_period: int = 50,
                 rsi_period: int = 7,
                 rsi_oversold: float = 30.0,
                 rsi_recovery: float = 45.0,
                 tp_percentage: float = 2.5,
                 max_down_streak: int = 3,
                 **kwargs):
        # Основные параметры стратегии
        self.momentum_period = momentum_period
        self.sma_trend_period = sma_trend_period
        self.rsi_period = rsi_period
        self.rsi_oversold = rsi_oversold
        self.rsi_recovery = rsi_recovery
        self.tp_percentage = tp_percentage
        self.max_down_streak = max_down_streak

        # Вспомогательные переменные
        self.position = None
        self.entry_price = None
        self.down_streak = 0

    @property
    def name(self) -> str:
        return self.__class__.__name__

    def analyze(self, historical_data: pd.DataFrame) -> dict:
        """
        Основной метод для анализа исторических данных и принятия решения о сделке.
        """
        required_data_length = max(self.sma_trend_period, self.momentum_period, self.rsi_period) + 2
        if len(historical_data) < required_data_length:
            return {'signal': 'hold'}

        close = historical_data['Close'].astype(float)

        sma = close.rolling(self.sma_trend_period).mean()
        momentum = close.diff(self.momentum_period)

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        ema_up = gain.ewm(com=self.rsi_period - 1, adjust=False).mean()
        ema_down = loss.ewm(com=self.rsi_period - 1, adjust=False).mean()
        rs = ema_up / (ema_down + 1e-8)
        rsi = 100 - (100 / (1 + rs))

        # Берём float напрямую, никаких .item()
        current_price = float(close.iloc[-1])
        current_rsi = float(rsi.iloc[-1])
        current_momentum = float(momentum.iloc[-1])
        current_sma = float(sma.iloc[-1])

        # --- Логика входа в покупку ---
        if current_rsi < self.rsi_oversold and current_momentum > 0 and current_price > current_sma:
            return {
                'signal': 'buy',
                'entry_price': current_price,
                'target_tp_price': current_price * (1 + self.tp_percentage / 100)
            }

        return {'signal': 'hold'}

    def generate_signals(self, ohlcv):
        """
        Метод для совместимости, фактически не используется в Playground.
        """
        pass
