# Файл: trading/analytics/metrics_calculator.py

import numpy as np
import pandas as pd
from dataclasses import dataclass

@dataclass
class PerformanceMetrics:
    """Структура для хранения рассчитанных метрик производительности."""
    total_return_pct: float  # Общая доходность в процентах
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float # Максимальная просадка в процентах
    calmar_ratio: float

class MetricsCalculator:
    """
    Калькулятор финансовых метрик с исправленной логикой расчетов.
    """
    def __init__(self, trade_history: list[dict], initial_balance: float, risk_free_rate: float = 0.0):
        self.initial_balance = initial_balance
        # Годовая безрисковая ставка, пересчитанная на дневную (если нужно, но для трейдинга часто оставляют 0)
        self.risk_free_rate_decimal = risk_free_rate / 252 # 252 торговых дня в году

        self.trade_history = [t for t in trade_history if t.get('timestamp') is not None]
        self.df = self._prepare_dataframe()

    def _prepare_dataframe(self) -> pd.DataFrame:
        """Подготавливает DataFrame из истории сделок."""
        if not self.trade_history:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.trade_history)
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df = df.set_index('timestamp').sort_index()
        
        df['pnl'] = df['profit'] # Используем уже рассчитанный PnL
        
        # --- ИСПРАВЛЕНИЕ: Рассчитываем доходность в виде десятичной дроби ---
        df['return_decimal'] = df['pnl'] / self.initial_balance
        
        return df

    def get_returns(self) -> pd.Series:
        """Возвращает серию ДЕСЯТИЧНЫХ доходов по сделкам."""
        return self.df['return_decimal'] if 'return_decimal' in self.df else pd.Series(dtype=float)

    def _calculate_sharpe_ratio(self) -> float:
        """Расчет Коэффициента Шарпа с защитой от экстремальных значений."""
        returns = self.get_returns()
        if len(returns) < 2: return 0.0
        
        std_dev = returns.std(ddof=1)
        
        # ЗАЩИТА: Минимальный порог для std_dev
        MIN_STD_DEV = 1e-10
        if std_dev < MIN_STD_DEV:
            std_dev = MIN_STD_DEV
        
        sharpe = (returns.mean() - self.risk_free_rate_decimal) / std_dev
        
        # ЗАЩИТА: Ограничиваем максимальное значение Sharpe
        MAX_SHARPE = 10.0
        return min(max(sharpe, -MAX_SHARPE), MAX_SHARPE)

    def _calculate_sortino_ratio(self) -> float:
        """[ИСПРАВЛЕНО] Расчет Коэффициента Сортино с адаптивной защитой."""
        returns = self.get_returns()
        if len(returns) < 2: return 0.0
        
        target_return = self.risk_free_rate_decimal
        downside_returns = returns[returns < target_return]
        
        # Если нет убытков - возвращаем разумное высокое значение
        if len(downside_returns) == 0:
            return 5.0  # Хорошо, но не максимум
        
        # Рассчитываем downside deviation разными способами
        if len(downside_returns) == 1:
            # Для 1 убытка - используем абсолютное значение
            downside_deviation = abs(downside_returns.iloc[0])
        elif len(downside_returns) < 5:
            # Для малого количества - среднее абсолютное отклонение
            downside_deviation = abs(downside_returns).mean()
        else:
            # Для большого количества - стандартное отклонение
            downside_deviation = downside_returns.std(ddof=1)
        
        # Минимальная защита от деления на очень маленькие числа
        min_deviation = max(1e-8, abs(returns.mean()) * 0.1)  # Адаптивный минимум
        if downside_deviation < min_deviation:
            downside_deviation = min_deviation
        
        sortino = (returns.mean() - target_return) / downside_deviation
        
        # Более мягкие ограничения в зависимости от количества сделок
        if len(returns) < 10:
            # Мало сделок - более строгие ограничения
            max_sortino = 3.0
        elif len(returns) < 20:
            max_sortino = 5.0
        else:
            max_sortino = 10.0
            
        return min(max(sortino, -max_sortino), max_sortino)

    def _calculate_max_drawdown_pct(self) -> float:
        """Расчет максимальной просадки в процентах."""
        if self.df.empty: return 0.0
        
        # Рассчитываем баланс после каждой сделки
        balance_over_time = self.initial_balance + self.df['pnl'].cumsum()
        # Находим пиковый баланс в каждой точке времени
        peak = balance_over_time.expanding(min_periods=1).max()
        # Рассчитываем просадку в деньгах
        drawdown_abs = peak - balance_over_time
        # Рассчитываем просадку в процентах от пика
        drawdown_pct = (drawdown_abs / peak) * 100
        
        return drawdown_pct.max() if not drawdown_pct.empty else 0.0

    def _calculate_calmar_ratio(self) -> float:
        """Расчет Коэффициента Кальмара."""
        if self.df.empty or len(self.get_returns()) < 2: return 0.0
        
        # Считаем среднегодовую доходность (упрощенно для бэктеста)
        total_return = self.df['pnl'].sum() / self.initial_balance
        num_days = (self.df.index[-1] - self.df.index[0]).days
        annualized_return = total_return * (365 / num_days) if num_days > 0 else total_return

        max_drawdown = self._calculate_max_drawdown_pct() / 100 # Нужна десятичная дробь
        if max_drawdown == 0.0: return 0.0
        
        return annualized_return / max_drawdown

    def calculate_all_metrics(self) -> PerformanceMetrics:
        """Рассчитывает все метрики и возвращает их в виде структуры."""
        if self.df.empty:
            return PerformanceMetrics(0.0, 0.0, 0.0, 0.0, 0.0)

        total_return_pct = (self.df['pnl'].sum() / self.initial_balance) * 100
        
        return PerformanceMetrics(
            total_return_pct=total_return_pct,
            sharpe_ratio=self._calculate_sharpe_ratio(),
            sortino_ratio=self._calculate_sortino_ratio(),
            max_drawdown_pct=self._calculate_max_drawdown_pct(),
            calmar_ratio=self._calculate_calmar_ratio()
        )