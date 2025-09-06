# Файл: trading/strategies/bb_macd_atr_strategy.py

import pandas as pd
from strategies.base_strategy import BaseStrategy

class Strategy(BaseStrategy):
    """
    Комплексная стратегия на основе Полос Боллинджера, MACD и ATR.
    
    Логика входа:
    1. Цена закрывается НИЖЕ нижней Полосы Боллинджера (сигнал о возможной перепроданности).
    2. Гистограмма MACD находится ВЫШЕ своей сигнальной линии (подтверждение бычьего момента).
    3. Линия MACD находится НИЖЕ нулевой линии (вход в начале потенциального разворота).
    """
    def __init__(self, 
                 bb_period=20, 
                 bb_std_dev=2.0, 
                 macd_fast=12, 
                 macd_slow=26, 
                 macd_signal=9,
                 atr_period=14,
                 tp_atr_multiplier=3.0):
        
        # Преобразуем параметры в правильные типы
        self.bb_period = int(bb_period)
        self.bb_std_dev = float(bb_std_dev)
        self.macd_fast = int(macd_fast)
        self.macd_slow = int(macd_slow)
        self.macd_signal = int(macd_signal)
        self.atr_period = int(atr_period)
        self.tp_atr_multiplier = float(tp_atr_multiplier)

        self._name = f"BB({self.bb_period},{self.bb_std_dev})_MACD({self.macd_fast},{self.macd_slow},{self.macd_signal})_ATR({self.atr_period})"

    @property
    def name(self) -> str:
        return self._name

    def _calculate_atr(self, high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> pd.Series:
        """Расчет Average True Range (ATR)."""
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())
        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        return tr.ewm(alpha=1/period, adjust=False).mean()

    def analyze(self, historical_data: pd.DataFrame) -> dict:
        # Проверяем, достаточно ли данных для всех индикаторов
        required_data_length = max(self.bb_period, self.macd_slow, self.atr_period) + 2
        if len(historical_data) < required_data_length:
            return {'signal': 'hold'}

        # --- Расчет индикаторов ---
        
        # 1. Полосы Боллинджера
        sma = historical_data['Close'].rolling(window=self.bb_period).mean()
        std = historical_data['Close'].rolling(window=self.bb_period).std()
        bollinger_lower = sma - (std * self.bb_std_dev)

        # 2. MACD
        ema_fast = historical_data['Close'].ewm(span=self.macd_fast, adjust=False).mean()
        ema_slow = historical_data['Close'].ewm(span=self.macd_slow, adjust=False).mean()
        macd_line = ema_fast - ema_slow
        signal_line = macd_line.ewm(span=self.macd_signal, adjust=False).mean()
        macd_histogram = macd_line - signal_line

        # 3. ATR
        atr = self._calculate_atr(historical_data['High'], historical_data['Low'], historical_data['Close'], self.atr_period)

        # Проверяем, что все последние значения индикаторов рассчитаны
        if any(pd.isna(val.values[-1]) for val in [bollinger_lower, macd_line, signal_line, atr]):
            return {'signal': 'hold'}

        # --- Логика принятия решения ---
        
        current_price = historical_data['Close'].values[-1]
        
        # Условия для входа в покупку
        cond1 = current_price < bollinger_lower.values[-1]
        cond2 = macd_histogram.values[-1] > 0 
        cond3 = macd_line.values[-1] < 0

        if cond1 and cond2 and cond3:
            # Используем ATR для динамического тейк-профита
            current_atr = atr.values[-1]
            target_tp = current_price + (current_atr * self.tp_atr_multiplier)
            
            return {
                'signal': 'buy',
                'entry_price': float(current_price),
                'target_tp_price': float(target_tp)
            }

        return {'signal': 'hold'}