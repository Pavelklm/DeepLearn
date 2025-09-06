# Файл: trading/optimizer.py

import optuna
import json
from objective_function import objective_function 
from bot_process import Playground
import logging
import time
from datetime import datetime, timedelta
import yfinance as yf
import pandas as pd
import argparse
import os
import numpy as np

# Настройка логирования
optuna.logging.set_verbosity(optuna.logging.WARNING)

# ==============================================================================
# 🚀 ШАГ 1: ПРЕДВАРИТЕЛЬНАЯ ЗАГРУЗКА ДАННЫХ  
# ==============================================================================
print("⏳ Загружаем исторические данные для walk-forward analysis...")
backtest_params = {
    "ticker": "BTC-USD",
    "period": "2y",
    "interval": "4h"
}
all_data = yf.download(
    tickers=backtest_params["ticker"],
    period=backtest_params["period"],
    interval=backtest_params["interval"],
    auto_adjust=True
)

if all_data is None or all_data.empty:
    print("❌ Не удалось загрузить данные. Проверьте тикер и подключение к сети.")
    exit()

print(f"✅ Данные загружены: {len(all_data)} свечей.")
print(f"📅 Период: {all_data.index[0].strftime('%Y-%m-%d')} → {all_data.index[-1].strftime('%Y-%m-%d')}")
print("="*80)


def run_walk_forward_optimization(all_data: pd.DataFrame, opt_config_path: str, n_trials_per_window: int = 100) -> dict:
    """
    Запускает Walk-Forward Analysis - оптимизацию на скользящих окнах.
    
    Args:
        all_data: Полный датасет
        opt_config_path: Путь к конфигурации оптимизации  
        n_trials_per_window: Количество итераций на каждое окно
    
    Returns:
        Словарь с результатами по всем окнам
    """
    print("\n" + "="*80)
    print("🔄 НАЧИНАЕМ WALK-FORWARD ANALYSIS (СКОЛЬЗЯЩИЕ ОКНА)")
    print("="*80)
    
    # Параметры окон
    train_window_months = 9  # 9 месяцев для обучения
    test_window_months = 3   # 3 месяца для теста
    step_months = 3          # Сдвиг на 3 месяца
    
    # Преобразуем в дни (примерно)
    train_window_days = train_window_months * 30
    test_window_days = test_window_months * 30  
    step_days = step_months * 30
    
    total_days = len(all_data)
    window_results = []
    
    print(f"📅 ПАРАМЕТРЫ ОКОН:")
    print(f"   🎯 Обучение: {train_window_months} мес. (~{train_window_days} дней)")
    print(f"   🔍 Тестирование: {test_window_months} мес. (~{test_window_days} дней)")
    print(f"   ➡️ Шаг сдвига: {step_months} мес. (~{step_days} дней)")
    print(f"   📊 Общие данные: {total_days} дней")
    
    # Вычисляем количество окон
    window_count = 0
    start_idx = 0
    
    while start_idx + train_window_days + test_window_days <= total_days:
        window_count += 1
        start_idx += step_days
    
    print(f"📊 КОЛИЧЕСТВО ОКОН: {window_count}")
    print(f"🔥 ОБЩИЕ ИТЕРАЦИИ: {window_count * n_trials_per_window}")
    print("\n" + "-"*80)
    
    # ==================================================================
    # 🔄 ОСНОВНОЙ ЦИКЛ: ПО КАЖДОМУ ОКНУ
    # ==================================================================
    
    start_idx = 0
    
    for window_num in range(1, window_count + 1):
        print(f"\n🗓️ ОКНО {window_num}/{window_count}:")
        
        # Определяем границы окна
        train_start = start_idx
        train_end = start_idx + train_window_days
        test_start = train_end
        test_end = test_start + test_window_days
        
        # Извлекаем данные
        train_data = all_data.iloc[train_start:train_end].copy()
        test_data = all_data.iloc[test_start:test_end].copy()
        
        train_period = f"{train_data.index[0].strftime('%Y-%m-%d')} → {train_data.index[-1].strftime('%Y-%m-%d')}"
        test_period = f"{test_data.index[0].strftime('%Y-%m-%d')} → {test_data.index[-1].strftime('%Y-%m-%d')}"
        
        print(f"   🎯 Обучение: {train_period} ({len(train_data)} свечей)")
        print(f"   🔍 Тест:       {test_period} ({len(test_data)} свечей)")
        
        # ==============================================================
        # 🚀 ОПТИМИЗАЦИЯ НА ОБУЧАЮЩИХ ДАННЫХ
        # ==============================================================
        
        print(f"   🚀 Оптимизация на {n_trials_per_window} итераций...")
        
        # Создаем отдельное исследование для каждого окна
        study_name = f'walk_forward_window_{window_num}_{int(time.time())}'
        study = optuna.create_study(direction='maximize', study_name=study_name)
        
        # Оптимизируем (без подробного лога)
        study.optimize(
            lambda trial: objective_function(trial, train_data, opt_config_path), 
            n_trials=n_trials_per_window,
            show_progress_bar=False  # Отключаем подробный лог
        )
        
        best_params = study.best_trial.params
        best_score = study.best_trial.value
        
        print(f"   ✅ Лучшие параметры: {best_params}")
        print(f"   📈 Лучшая оценка: {best_score:.4f}")
        
        # ==============================================================
        # 🔍 ТЕСТИРОВАНИЕ НА НЕПРЕДВИДЕННЫХ ДАННЫХ
        # ==============================================================
        
        print(f"   🔍 Тестирование на непредвиденных данных...")
        
        # Загружаем конфигурацию стратегии
        with open(opt_config_path, 'r', encoding='utf-8') as f:
            opt_config = json.load(f)
        
        test_config = {
            "bot_name": f"WalkForward_W{window_num}_Test_{int(time.time())}",
            "strategy_file": opt_config["strategy_file"],
            "risk_config_file": "configs/live_default.json",
            "strategy_params": best_params,
            "generate_chart": False  # Отключаем графики для скорости
        }
        
        try:
            test_playground = Playground(test_config, test_config['bot_name'], test_data)
            test_playground.run()
            
            # Получаем результаты теста
            test_history = test_playground.risk_manager.performance_tracker.trade_history
            test_history_dicts = [trade.__dict__ for trade in test_history]
            
            from analytics.metrics_calculator import MetricsCalculator
            from risk_management.config_manager import ConfigManager
            
            base_config = ConfigManager.load_config(test_config['risk_config_file'])
            initial_balance = base_config.trading.initial_balance
            
            if len(test_history_dicts) > 0:
                test_calculator = MetricsCalculator(trade_history=test_history_dicts, initial_balance=initial_balance)
                test_metrics = test_calculator.calculate_all_metrics()
                
                test_profit = sum(t['profit'] for t in test_history_dicts)
                test_trades = len(test_history_dicts)
                test_win_rate = (sum(1 for t in test_history_dicts if t['success']) / test_trades * 100) if test_trades > 0 else 0
                test_max_drawdown = test_metrics.max_drawdown_pct
                
                print(f"   💰 Прибыль: ${test_profit:.2f} ({test_profit/initial_balance*100:+.2f}%)")
                print(f"   📊 Сделок: {test_trades} | Win Rate: {test_win_rate:.1f}%")
                print(f"   📈 Sharpe: {test_metrics.sharpe_ratio:.3f} | Drawdown: {test_max_drawdown:.2f}%")
                
                window_result = {
                    'window_num': window_num,
                    'train_period': train_period,
                    'test_period': test_period,
                    'best_params': best_params,
                    'optimization_score': best_score,
                    'test_profit': test_profit,
                    'test_profit_pct': test_profit/initial_balance*100,
                    'test_trades': test_trades,
                    'test_win_rate': test_win_rate,
                    'test_sharpe': test_metrics.sharpe_ratio,
                    'test_sortino': test_metrics.sortino_ratio,
                    'test_calmar': test_metrics.calmar_ratio,
                    'test_max_drawdown': test_max_drawdown,
                    'success': True
                }
                
            else:
                print(f"   ❌ Нет сделок на тестовых данных")
                window_result = {
                    'window_num': window_num,
                    'train_period': train_period, 
                    'test_period': test_period,
                    'best_params': best_params,
                    'optimization_score': best_score,
                    'test_profit': 0,
                    'test_profit_pct': 0,
                    'test_trades': 0,
                    'test_win_rate': 0,
                    'test_sharpe': 0,
                    'test_sortino': 0,
                    'test_calmar': 0,
                    'test_max_drawdown': 0,
                    'success': False
                }
                
        except Exception as e:
            print(f"   ❌ Ошибка при тестировании: {e}")
            window_result = {
                'window_num': window_num,
                'train_period': train_period,
                'test_period': test_period, 
                'best_params': best_params,
                'optimization_score': best_score,
                'test_profit': 0,
                'test_profit_pct': 0,
                'test_trades': 0,
                'test_win_rate': 0,
                'test_sharpe': 0,
                'test_sortino': 0,
                'test_calmar': 0,
                'test_max_drawdown': 0,
                'success': False,
                'error': str(e)
            }
        
        window_results.append(window_result)
        
        # Сдвигаем окно
        start_idx += step_days
        
        print(f"   ✅ Окно {window_num} завершено!")
    
    return {
        'windows': window_results,
        'total_windows': window_count,
        'trials_per_window': n_trials_per_window
    }


def analyze_overfitting(walk_forward_results: dict) -> dict:
    """
    Анализирует результаты walk-forward на предмет переобучения.
    
    Returns:
        Словарь с анализом переобучения
    """
    windows = walk_forward_results['windows']
    
    print("\n" + "="*80)
    print("🧐 АНАЛИЗ ПЕРЕОБУЧЕНИЯ (OVERFITTING ANALYSIS)")
    print("="*80)
    
    # Извлекаем результаты
    profits = [w['test_profit_pct'] for w in windows if w['success']]
    trades = [w['test_trades'] for w in windows if w['success']]
    win_rates = [w['test_win_rate'] for w in windows if w['success']]
    sharpe_ratios = [w['test_sharpe'] for w in windows if w['success']]
    
    successful_windows = len(profits)
    total_windows = len(windows)
    
    print(f"\n📊 ОБЩАЯ СТАТИСТИКА:")
    print(f"   ✅ Успешных окон: {successful_windows}/{total_windows} ({successful_windows/total_windows*100:.1f}%)")
    
    if successful_windows == 0:
        print("❌ НЕТ УСПЕШНЫХ ОКОН! Стратегия полностью провалена.")
        return {'overfitting_score': 100, 'verdict': 'КРИТИЧЕСКИЙ ПРОВАЛ'}
    
    # Статистика по прибыли
    mean_profit = np.mean(profits)
    std_profit = np.std(profits)
    profit_cv = (std_profit / abs(mean_profit) * 100) if mean_profit != 0 else 999
    
    profitable_windows = sum(1 for p in profits if p > 0)
    profit_consistency = profitable_windows / successful_windows * 100
    
    print(f"\n💰 АНАЛИЗ ПРИБЫЛЬНОСТИ:")
    print(f"   📈 Средняя прибыль: {mean_profit:.2f}% ± {std_profit:.2f}%")
    print(f"   📊 Прибыльных окон: {profitable_windows}/{successful_windows} ({profit_consistency:.1f}%)")
    print(f"   🎯 Коэффициент вариации: {profit_cv:.1f}%")
    
    # Детальные результаты по окнам
    print(f"\n🗓️ РЕЗУЛЬТАТЫ ПО ОКНАМ:")
    for i, window in enumerate(windows, 1):
        if window['success']:
            status = "✅" if window['test_profit_pct'] > 0 else "❌"
            print(f"   {status} Окно {i}: {window['test_profit_pct']:+.2f}% ({window['test_trades']} сделок, WR: {window['test_win_rate']:.1f}%)")
        else:
            print(f"   ❌ Окно {i}: ПРОВАЛ (нет сделок или ошибка)")
    
    # Расчет оценки переобучения
    losing_windows_penalty = (total_windows - profitable_windows) / total_windows * 100
    volatility_penalty = min(profit_cv, 100)
    consistency_bonus = profit_consistency
    
    overfitting_score = (
        losing_windows_penalty * 0.4 +  # 40% - штраф за убыточные окна
        volatility_penalty * 0.4 +      # 40% - штраф за нестабильность
        (100 - consistency_bonus) * 0.2  # 20% - штраф за непоследовательность
    )
    
    print(f"\n🎯 ОЦЕНКА ПЕРЕОБУЧЕНИЯ: {overfitting_score:.1f}%")
    
    # Вердикт
    if overfitting_score < 20:
        verdict = "🟢 ОТЛИЧНАЯ стратегия! Минимальное переобучение"
        recommendation = "Стратегия стабильна во времени и готова к использованию."
    elif overfitting_score < 40:
        verdict = "🟡 ПРИЕМЛЕМАЯ стратегия. Умеренная стабильность"
        recommendation = "Стратегия показывает неплохие результаты, но требует осторожности."
    elif overfitting_score < 70:
        verdict = "🟠 СОМНИТЕЛЬНАЯ стратегия. Признаки переобучения"
        recommendation = "Стратегия нестабильна. Рекомендуется доработка параметров."
    else:
        verdict = "🔴 ПЛОХАЯ стратегия! Критическое переобучение"
        recommendation = "Стратегия переобучена. Нужен пересмотр подхода или больше данных."
    
    print(f"\n{verdict}")
    print(f"💡 {recommendation}")
    
    # Дополнительные проверки
    if mean_profit > 50:
        print(f"⚠️  ПОДОЗРЕНИЕ: Средняя прибыль {mean_profit:.1f}% слишком высока для реального рынка!")
    
    if profit_cv > 200:
        print(f"⚠️  НЕСТАБИЛЬНОСТЬ: Коэффициент вариации {profit_cv:.1f}% указывает на хаотичное поведение!")
    
    print("\n" + "="*80)
    
    return {
        'overfitting_score': overfitting_score,
        'verdict': verdict,
        'successful_windows': successful_windows,
        'total_windows': total_windows,
        'mean_profit': mean_profit,
        'profit_consistency': profit_consistency,
        'profit_cv': profit_cv,
        'recommendation': recommendation
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Walk-Forward оптимизатор торговых стратегий.")
    parser.add_argument(
        "config", 
        help="Путь к JSON файлу с конфигурацией оптимизации (например, configs/optimizer/ema_crossover.json)."
    )
    parser.add_argument(
        "--trials", 
        type=int, 
        default=100,
        help="Количество итераций на каждое окно."
    )
    args = parser.parse_args()

    with open(args.config, 'r', encoding='utf-8') as f:
        opt_config = json.load(f)
    strategy_name = opt_config.get("strategy_file", "champion")

    # Запускаем walk-forward analysis
    walk_forward_results = run_walk_forward_optimization(
        all_data=all_data, 
        opt_config_path=args.config, 
        n_trials_per_window=args.trials
    )
    
    # Анализируем переобучение
    overfitting_analysis = analyze_overfitting(walk_forward_results)
    
    print(f"\n🎉 WALK-FORWARD ANALYSIS ЗАВЕРШЕН!")
    print(f"Результаты сохранены в памяти для дальнейшего анализа.")
