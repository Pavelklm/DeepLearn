# Файл: trading/analytics/metrics_calculator.py

import pandas as pd
import numpy as np
from typing import List, Dict, Any

class Metrics:
    def __init__(self):
        self.sharpe_ratio = 0.0
        self.sortino_ratio = 0.0
        self.calmar_ratio = 0.0
        self.total_return_pct = 0.0
        self.max_drawdown_pct = 0.0
        # ... можно добавить другие метрики

class MetricsCalculator:
    def __init__(self, trade_history: List[Dict[str, Any]], initial_balance: float, risk_free_rate: float = 0.0):
        self.trade_history = trade_history
        self.initial_balance = initial_balance
        self.risk_free_rate = risk_free_rate
        self.df = self._prepare_dataframe()
        
        # Разумные ограничения для коэффициентов
        self.MAX_SHARPE = 10.0
        self.MAX_SORTINO = 15.0
        self.MAX_CALMAR = 20.0

    def _prepare_dataframe(self) -> pd.DataFrame:
        if not self.trade_history:
            return pd.DataFrame()
        
        df = pd.DataFrame(self.trade_history)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'])
            df = df.sort_values(by='timestamp').set_index('timestamp')
        
        df['pnl'] = df['profit']
        df['cumulative_pnl'] = df['pnl'].cumsum()
        df['balance'] = self.initial_balance + df['cumulative_pnl']
        df['daily_return'] = df['balance'].pct_change().fillna(0)
        
        return df

    def _normalize_by_trade_count(self, ratio: float) -> float:
        """
        Нормализует коэффициенты в зависимости от количества сделок.
        Меньше сделок = менее надежная статистика = штраф.
        """
        if self.df.empty:
            return 0.0
            
        trade_count = len(self.trade_history)
        
        # Штраф за малое количество сделок
        if trade_count < 20:
            penalty_factor = trade_count / 20.0  # От 0.05 до 1.0
            ratio *= penalty_factor
        
        return ratio

    def calculate_sharpe_ratio(self) -> float:
        if self.df.empty or self.df['daily_return'].std() == 0:
            return 0.0
        
        excess_returns = self.df['daily_return'] - self.risk_free_rate
        
        # Если волатильность слишком мала (стратегия почти не торгует)
        std_returns = excess_returns.std()
        if std_returns < 1e-6:
            return 0.0
        
        # Предполагаем 252 торговых дня в году
        sharpe_ratio = excess_returns.mean() / std_returns * np.sqrt(252)
        
        # Проверяем на конечность и ограничиваем разумными пределами
        if not np.isfinite(sharpe_ratio):
            return 0.0
            
        # Применяем ограничения и нормализацию
        sharpe_ratio = min(abs(sharpe_ratio), self.MAX_SHARPE) * np.sign(sharpe_ratio)
        sharpe_ratio = self._normalize_by_trade_count(sharpe_ratio)
        
        return sharpe_ratio

    def calculate_sortino_ratio(self) -> float:
        """
        ИСПРАВЛЕННЫЙ РАСЧЕТ СОРТИНО:
        Убираем магические числа, добавляем разумные ограничения.
        """
        if self.df.empty:
            return 0.0

        target_return = self.risk_free_rate
        excess_returns = self.df['daily_return'] - target_return
        
        # Вычисляем стандартное отклонение только для отрицательных доходностей
        downside_returns = excess_returns[excess_returns < 0]
        
        # Если убыточных периодов нет, но есть прибыль - хорошо, но не фантастично
        if len(downside_returns) == 0:
            if excess_returns.mean() > 0:
                # Возвращаем высокое, но разумное значение
                sortino_ratio = self.MAX_SORTINO
            else:
                return 0.0
        else:
            downside_std = downside_returns.std()
            if downside_std == 0:
                return 0.0
            
            sortino_ratio = excess_returns.mean() / downside_std * np.sqrt(252)
        
        # Проверяем на конечность и ограничиваем
        if not np.isfinite(sortino_ratio):
            return 0.0
            
        # Применяем ограничения и нормализацию
        sortino_ratio = min(abs(sortino_ratio), self.MAX_SORTINO) * np.sign(sortino_ratio)
        sortino_ratio = self._normalize_by_trade_count(sortino_ratio)
        
        return sortino_ratio

    def calculate_total_return_pct(self) -> float:
        """Рассчитывает общую доходность в процентах."""
        if self.df.empty:
            return 0.0
        total_profit = self.df['pnl'].sum()
        return (total_profit / self.initial_balance) * 100

    def calculate_max_drawdown_pct(self) -> float:
        """Рассчитывает максимальную просадку в процентах."""
        if self.df.empty:
            return 0.0
        
        cumulative_max = self.df['balance'].cummax()
        drawdown = (self.df['balance'] - cumulative_max) / cumulative_max
        max_drawdown = drawdown.min()
        return abs(max_drawdown) * 100

    def calculate_calmar_ratio(self) -> float:
        """
        ИСПРАВЛЕННЫЙ РАСЧЕТ КАЛЬМАРА:
        Убираем магические числа, добавляем разумную логику.
        """
        if self.df.empty:
            return 0.0

        cumulative_max = self.df['balance'].cummax()
        drawdown = (self.df['balance'] - cumulative_max) / cumulative_max
        max_drawdown = drawdown.min()

        annualized_return = self.df['daily_return'].mean() * 252
        
        # Если просадки нет, но есть прибыль - отлично, но не бесконечно
        if max_drawdown == 0:
            if annualized_return > 0:
                calmar_ratio = self.MAX_CALMAR
            else:
                return 0.0
        else:
            calmar_ratio = annualized_return / abs(max_drawdown)
        
        # Проверяем на конечность и ограничиваем
        if not np.isfinite(calmar_ratio):
            return 0.0
            
        # Применяем ограничения и нормализацию
        calmar_ratio = min(abs(calmar_ratio), self.MAX_CALMAR) * np.sign(calmar_ratio)
        calmar_ratio = self._normalize_by_trade_count(calmar_ratio)
        
        return calmar_ratio

    def calculate_all_metrics(self) -> "Metrics":
        metrics = Metrics()
        if not self.trade_history:
            return metrics
            
        metrics.sharpe_ratio = self.calculate_sharpe_ratio()
        metrics.sortino_ratio = self.calculate_sortino_ratio()
        metrics.calmar_ratio = self.calculate_calmar_ratio()
        metrics.total_return_pct = self.calculate_total_return_pct()
        metrics.max_drawdown_pct = self.calculate_max_drawdown_pct()
        
        # Округляем для красивого вывода
        metrics.sharpe_ratio = round(metrics.sharpe_ratio, 4)
        metrics.sortino_ratio = round(metrics.sortino_ratio, 4)
        metrics.calmar_ratio = round(metrics.calmar_ratio, 4)
        metrics.total_return_pct = round(metrics.total_return_pct, 2)
        metrics.max_drawdown_pct = round(metrics.max_drawdown_pct, 2)

        return metrics