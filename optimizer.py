# Файл: trading/optimizer.py

import optuna
from objective_function import objective_function 
from bot_process import Playground
import logging
import time
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd

# Настройка логирования
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ==============================================================================
# 🚀 ШАГ 1: ПРЕДВАРИТЕЛЬНАЯ ЗАГРУЗКА ДАННЫХ
# ==============================================================================
print("⏳ Загружаем исторические данные для оптимизации...")
backtest_params = {
    "ticker": "BTC-USD",
    "period": "2y",
    "interval": "4h"
}
ohlcv_data = yf.download(
    tickers=backtest_params["ticker"],
    period=backtest_params["period"],
    interval=backtest_params["interval"],
    auto_adjust=True
)

if ohlcv_data is None or ohlcv_data.empty:
    print("❌ Не удалось загрузить данные. Проверьте тикер и подключение к сети.")
    exit()

print(f"✅ Данные загружены: {len(ohlcv_data)} свечей.")

# Глобальные переменные для отслеживания времени
start_time = None
trial_times = []

# Callback для показа прогресса
def progress_callback(study, trial):
    """
    Отображает прогресс оптимизации с детальной статистикой и ETA.
    """
    global start_time, trial_times
    
    if start_time is None:
        start_time = time.time()
    
    current_time = time.time()
    trial_times.append(current_time)
    
    if len(trial_times) > 0:
        avg_time_per_trial = (current_time - start_time) / len(study.trials)
        total_trials = study.user_attrs.get("n_trials", "N/A")
        if isinstance(total_trials, int):
            remaining_trials = total_trials - len(study.trials)
            eta_seconds = remaining_trials * avg_time_per_trial
            eta_str = f" | ETA: {str(timedelta(seconds=int(eta_seconds)))}"
            progress_str = f"{len(study.trials)}/{total_trials}"
        else:
            eta_str = ""
            progress_str = f"{len(study.trials)}"
    else:
        eta_str = ""
        progress_str = f"{len(study.trials)}"

    elapsed = str(timedelta(seconds=int(current_time - start_time)))
    
    print("-" * 80)
    print(f"📊 Прогресс: {progress_str} | Время: {elapsed}{eta_str}")
    current_sharpe = trial.value if trial.value is not None else -100.0
    print(f"📈 Sharpe Ratio - Лучший: {study.best_value:.4f} | Текущий: {current_sharpe:.4f}")
    
    current_trades = trial.user_attrs.get("trade_count", "N/A")
    
    if current_trades != "N/A" and current_trades > 1:
        current_winrate = trial.user_attrs.get("win_rate", 0)
        current_profit = trial.user_attrs.get("total_profit", 0)
        current_sortino = trial.user_attrs.get("sortino_ratio", 0)
        current_calmar = trial.user_attrs.get("calmar_ratio", 0)
        print(f"🎯 Текущий trial:")
        print(f"   Сделок: {current_trades} | Win Rate: {current_winrate:.1f}% | Прибыль: ${current_profit:.2f}")
        print(f"   Коэффициент Сортино: {current_sortino:.3f} | Коэффициент Кальмара: {current_calmar:.3f}")
    else:
        print(f"🎯 Текущий trial: Недостаточно сделок ({current_trades})")
    
    if study.best_trial and study.best_trial.user_attrs:
        best_trades = study.best_trial.user_attrs.get("trade_count", "N/A")
        if best_trades != "N/A" and best_trades > 1:
            best_winrate = study.best_trial.user_attrs.get("win_rate", 0)
            best_profit = study.best_trial.user_attrs.get("total_profit", 0)
            best_sortino = study.best_trial.user_attrs.get("sortino_ratio", 0)
            best_calmar = study.best_trial.user_attrs.get("calmar_ratio", 0)
            print(f"🏆 Лучший trial:")
            print(f"   Сделок: {best_trades} | Win Rate: {best_winrate:.1f}% | Прибыль: ${best_profit:.2f}")
            print(f"   Коэффициент Сортино: {best_sortino:.3f} | Коэффициент Кальмара: {best_calmar:.3f}")
        else:
            print(f"🏆 Лучший trial: Данные недоступны")
    
    # --- ИСПРАВЛЕНИЕ #1: Используем правильные ключи ---
    if study.best_params:
        best_fast = study.best_params.get('fast_ema_period', 'N/A')
        best_slow = study.best_params.get('slow_ema_period', 'N/A')
        best_tp = study.best_params.get('tp_multiplier', 0)
        print(f"⚙️ Лучшие параметры: EMA({best_fast}/{best_slow}) | TP={best_tp:.3f}")
    
    current_fast = trial.params.get('fast_ema_period', 'N/A')
    current_slow = trial.params.get('slow_ema_period', 'N/A')
    current_tp = trial.params.get('tp_multiplier', 0)
    print(f"🔧 Текущие параметры: EMA({current_fast}/{current_slow}) | TP={current_tp:.3f}")
    
    print("-" * 80)


def run_optimization(n_trials: int, data: pd.DataFrame, storage_name: str | None = None) -> optuna.trial.FrozenTrial:
    global start_time, trial_times
    start_time = time.time()
    trial_times = []

    print(f"🚀 НАЧИНАЕМ ОПТИМИЗАЦИЮ НА {n_trials} ИТЕРАЦИЙ...")
    print("📋 Параметры поиска: EMA от 5-50/15-200, TP от 1.01-1.20")
    print("=" * 80)

    if storage_name is None:
        storage_name = f'sqlite:///trading_optimization_{int(start_time)}.db'

    study_name = f'ema_crossover_btc_{int(start_time)}'
    study = optuna.create_study(
        direction='maximize',
        study_name=study_name,
        storage=storage_name
    )
    
    study.set_user_attr("n_trials", n_trials)
    
    study.optimize(lambda trial: objective_function(trial, data), n_trials=n_trials, callbacks=[progress_callback])

    print("\n" + "="*50)
    print("🏆 ОПТИМИЗАЦИЯ ЗАВЕРШЕНА 🏆")
    best_trial = study.best_trial
    print(f"Количество завершенных испытаний: {len(study.trials)}")
    print(f"\nЛучшее значение (Sharpe Ratio): {best_trial.value:.4f}")
    
    print("\nЗОЛОТЫЕ ПАРАМЕТРЫ:")
    for key, value in best_trial.params.items():
        print(f"     - {key}: {value}")
    print("="*50)

    return best_trial


if __name__ == "__main__":
    best_trial_result = run_optimization(n_trials=100, data=ohlcv_data) # Установите нужное число
    best_params = best_trial_result.params
    
    # --- ИСПРАВЛЕНИЕ #2: Используем правильные ключи ---
    champion_strategy_params = {
        "fast_ema_period": best_params['fast_ema_period'],
        "slow_ema_period": best_params['slow_ema_period'],
        "tp_multiplier": best_params['tp_multiplier']
    }
    
    champion_config = {
        "bot_name": f"Champion_EMA_{best_params['fast_ema_period']}_{best_params['slow_ema_period']}",
        "strategy_file": "ema_crossover_strategy",
        "risk_config_file": "configs/live_default.json",
        "strategy_params": champion_strategy_params,
        "generate_chart": True
    }

    print("\n📊 Создаем отчет и график для лучшей стратегии...")

    try:
        final_run_data = ohlcv_data.copy()

        champion_playground = Playground(champion_config, champion_config['bot_name'], final_run_data)
        champion_playground.run()
        print("✅ Отчет и график для чемпиона успешно созданы.")
    except Exception as e:
        print(f"❌ Не удалось создать финальный отчет: {e}")