import pandas as pd
import numpy as np
import os

from bot_process import Playground
from strategies.ema_crossover_strategy import Strategy
from analytics.metrics_calculator import MetricsCalculator
from risk_management.config_manager import ConfigManager, Config

def objective_function(trial, ohlcv_data: pd.DataFrame):
    """
    Целевая функция для оптимизатора Optuna.
    """
    fast_ema = trial.suggest_int('fast_ema_period', 5, 50)
    slow_ema = trial.suggest_int('slow_ema_period', fast_ema + 10, 200)
    tp_multiplier = trial.suggest_float('tp_multiplier', 1.01, 1.20, step=0.001)

    strategy_params = {
        "fast_ema_period": fast_ema,
        "slow_ema_period": slow_ema,
        "tp_multiplier": tp_multiplier
    }
    
    bot_name = f"optimizer_trial_{trial.number}"
    bot_config = {
        "bot_name": bot_name,
        "strategy_file": "ema_crossover_strategy",
        "symbol": "BTC-USD",
        "strategy_params": strategy_params,
        "risk_config_file": 'configs/live_default.json'
    }

    backtest = Playground(
        ohlcv_data=ohlcv_data,
        bot_config=bot_config,
        bot_name=bot_name
    )
    
    backtest.run()
    trade_history = backtest.risk_manager.performance_tracker.trade_history
    trade_history_dicts = [trade.__dict__ for trade in trade_history]
    
    # --- ИЗМЕНЕНИЯ ЗДЕСЬ ---
    
    # Если сделок мало, сохраняем это в trial и выходим
    if len(trade_history_dicts) < 2:
        trial.set_user_attr('trade_count', len(trade_history_dicts))
        return -10.0

    base_config = ConfigManager.load_config(bot_config['risk_config_file'])
    initial_balance = base_config.trading.initial_balance
    
    metrics_calculator = MetricsCalculator(trade_history=trade_history_dicts, initial_balance=initial_balance)
    metrics = metrics_calculator.calculate_all_metrics()
    
    # Считаем дополнительные метрики для отчета
    total_trades = len(trade_history_dicts)
    winning_trades = sum(1 for t in trade_history_dicts if t['success'])
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
    total_profit = sum(t['profit'] for t in trade_history_dicts)

    # Сохраняем все нужные данные в атрибутах trial
    trial.set_user_attr('sharpe_ratio', metrics.sharpe_ratio)
    trial.set_user_attr('sortino_ratio', metrics.sortino_ratio)
    trial.set_user_attr('calmar_ratio', metrics.calmar_ratio)
    trial.set_user_attr('trade_count', total_trades)
    trial.set_user_attr('win_rate', win_rate)
    trial.set_user_attr('total_profit', total_profit)

    sharpe_ratio = metrics.sharpe_ratio
    if pd.isna(sharpe_ratio) or not np.isfinite(sharpe_ratio):
        return -10.0
        
    return sharpe_ratio