# Файл: trading/optimizer.py

import optuna
import json
import logging
import time
from datetime import datetime
import yfinance as yf
import pandas as pd
import argparse
import numpy as np
from tqdm import tqdm
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from objective_function import objective_function
from bot_process import Playground

# ---------------------------------------
# Настройки
# ---------------------------------------
TRAIN_MONTHS = 9
TEST_MONTHS = 3
STEP_MONTHS = 3
DEFAULT_TRIALS = 100
CHARTS_DIR = Path('charts')
CHARTS_DIR.mkdir(exist_ok=True)

optuna.logging.set_verbosity(optuna.logging.WARNING)
try:
    plt.style.use('seaborn-v0_8')
except:
    plt.style.use('seaborn')
sns.set_palette("husl")


# ---------------------------------------
# Загрузка исторических данных
# ---------------------------------------
def load_data(ticker="BTC-USD", period="2y", interval="1h") -> pd.DataFrame:
    print("⏳ Загружаем исторические данные для walk-forward analysis...")
    df = yf.download(tickers=ticker, period=period, interval=interval, auto_adjust=True)
    if df is None or df.empty:
        raise ValueError("❌ Не удалось загрузить данные. Проверьте тикер и подключение к сети.")
    print(f"✅ Данные загружены: {len(df)} свечей ({df.index[0].date()} → {df.index[-1].date()})")
    return df


# ---------------------------------------
# Вспомогательные функции
# ---------------------------------------
def make_window_result(window_num, train_period, test_period, best_params, score,
                       trades=None, initial_balance=None, error=None):
    """Формирует результат окна walk-forward"""

    safe_balance = float(initial_balance) if initial_balance is not None else 1.0

    if trades and len(trades) > 0:
        profit = sum(t['profit'] for t in trades)
        total_trades = len(trades)
        win_rate = sum(1 for t in trades if t['success']) / total_trades * 100
        from analytics.metrics_calculator import MetricsCalculator
        metrics = MetricsCalculator(trades, safe_balance).calculate_all_metrics()
        return {
            'window_num': window_num,
            'train_period': train_period,
            'test_period': test_period,
            'best_params': best_params,
            'optimization_score': score,
            'test_profit': profit,
            'test_profit_pct': profit/safe_balance*100,
            'test_trades': total_trades,
            'test_win_rate': win_rate,
            'test_sharpe': metrics.sharpe_ratio,
            'test_sortino': metrics.sortino_ratio,
            'test_calmar': metrics.calmar_ratio,
            'test_max_drawdown': metrics.max_drawdown_pct,
            'success': True
        }
    else:
        return {
            'window_num': window_num,
            'train_period': train_period,
            'test_period': test_period,
            'best_params': best_params,
            'optimization_score': score,
            'test_profit': 0,
            'test_profit_pct': 0,
            'test_trades': 0,
            'test_win_rate': 0,
            'test_sharpe': 0,
            'test_sortino': 0,
            'test_calmar': 0,
            'test_max_drawdown': 0,
            'success': False,
            'error': str(error) if error else None
        }


# ---------------------------------------
# Walk-forward оптимизация
# ---------------------------------------
def run_walk_forward(all_data, config_path, n_trials=DEFAULT_TRIALS):
    """Основной pipeline walk-forward анализа"""
    print("\n🔄 НАЧИНАЕМ WALK-FORWARD ANALYSIS")
    with open(config_path, 'r', encoding='utf-8') as f:
        opt_config = json.load(f)

    start_date = all_data.index[0]
    end_date = all_data.index[-1]
    windows = []

    current_train_start = start_date
    while True:
        train_end = current_train_start + pd.DateOffset(months=TRAIN_MONTHS)
        test_start = train_end
        test_end = test_start + pd.DateOffset(months=TEST_MONTHS)
        if test_end > end_date:
            break
        windows.append((current_train_start, train_end, test_start, test_end))
        current_train_start += pd.DateOffset(months=STEP_MONTHS)

    window_results = []
    best_overall_score = -np.inf
    best_overall_params = {}

    for idx, (train_start, train_end, test_start, test_end) in enumerate(windows, 1):
        print(f"\n🗓️ ОКНО {idx}/{len(windows)}")
        train_data = all_data.loc[train_start:train_end]
        test_data = all_data.loc[test_start:test_end]

        train_period = f"{train_data.index[0].date()} → {train_data.index[-1].date()}"
        test_period = f"{test_data.index[0].date()} → {test_data.index[-1].date()}"

        # ===== Оптимизация =====
        study = optuna.create_study(direction='maximize', study_name=f"WF_{idx}_{int(time.time())}")
        with tqdm(total=n_trials, desc=f"      🔍 Окно {idx}", leave=False, ncols=80) as pbar:
            def cb(study, trial):
                pbar.update(1)
                if trial.value is not None:
                    pbar.set_postfix({'Best': f"{study.best_value:.3f}", 'Curr': f"{trial.value:.3f}"})
            study.optimize(lambda trial: objective_function(trial, train_data, config_path),
                           n_trials=n_trials, callbacks=[cb])

        best_params = study.best_trial.params
        best_score = study.best_trial.value
        if best_score is not None and (best_overall_score is None or best_score > best_overall_score):
            best_overall_score = best_score
            best_overall_params = best_params

        # ===== Тестирование =====
        try:
            test_cfg = {
                "bot_name": f"WF_{idx}_Test_{int(time.time())}",
                "strategy_file": opt_config["strategy_file"],
                "risk_config_file": "configs/live_default.json",
                "strategy_params": best_params,
                "generate_chart": False
            }
            test_bot = Playground(test_cfg, test_cfg['bot_name'], test_data)
            test_bot.run()
            trades = [t.__dict__ for t in test_bot.risk_manager.performance_tracker.trade_history]

            from risk_management.config_manager import ConfigManager
            base_cfg = ConfigManager.load_config(test_cfg['risk_config_file'])
            initial_balance = base_cfg.trading.initial_balance
            window_result = make_window_result(idx, train_period, test_period, best_params, best_score, trades, initial_balance)
        except Exception as e:
            print(f"   ❌ Ошибка теста: {e}")
            window_result = make_window_result(idx, train_period, test_period, best_params, best_score, error=e)

        window_results.append(window_result)

    return {
        'windows': window_results,
        'total_windows': len(windows),
        'trials_per_window': n_trials,
        'best_overall_params': best_overall_params
    }


# ---------------------------------------
# Основной pipeline
# ---------------------------------------
def run_pipeline(config_path, trials=DEFAULT_TRIALS, ticker="BTC-USD"):
    all_data = load_data(ticker)
    strategy_name = Path(config_path).stem

    start_time = time.time()
    results = run_walk_forward(all_data, config_path, trials)
    duration = time.time() - start_time

    # --- Сводка, графики и анализ переобучения ---
    from optimizer_utils import print_detailed_summary, generate_walk_forward_charts, analyze_overfitting, run_champion_backtest

    print_detailed_summary(results)
    generate_walk_forward_charts(results, strategy_name)
    if results['best_overall_params']:
        run_champion_backtest(results['best_overall_params'], strategy_name, all_data, config_path)
    overfitting_analysis = analyze_overfitting(results)

    print(f"\n🎉 WALK-FORWARD ANALYSIS ЗАВЕРШЕН")
    print(f"⏱️ Время выполнения: {duration/60:.1f} мин")
    return results, overfitting_analysis


# ---------------------------------------
# Точка входа
# ---------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Walk-Forward оптимизатор торговых стратегий.")
    parser.add_argument("config", help="Путь к JSON файлу с конфигурацией стратегии.")
    parser.add_argument("--trials", type=int, default=DEFAULT_TRIALS)
    parser.add_argument("--ticker", type=str, default="BTC-USD")
    args = parser.parse_args()

    run_pipeline(args.config, args.trials, args.ticker)
