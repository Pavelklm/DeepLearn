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
from tqdm import tqdm
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path

# Настройка логирования
optuna.logging.set_verbosity(optuna.logging.WARNING)
try:
    plt.style.use('seaborn-v0_8')
except:
    plt.style.use('seaborn')
sns.set_palette("husl")

# ==============================================================================
# 🚀 ШАГ 1: ПРЕДВАРИТЕЛЬНАЯ ЗАГРУЗКА ДАННЫХ  
# ==============================================================================
print("⏳ Загружаем исторические данные для walk-forward analysis...")
backtest_params = {
    "ticker": "BTC-USD",
    "period": "2y",
    "interval": "1h"
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


def generate_walk_forward_charts(walk_forward_results: dict, strategy_name: str) -> None:
    """
    Генерирует красивые графики для walk-forward анализа.
    """
    windows = walk_forward_results['windows']
    
    # Создаем папку для графиков
    charts_dir = Path('charts')
    charts_dir.mkdir(exist_ok=True)
    
    # Извлекаем данные
    successful_windows = [w for w in windows if w['success']]
    window_nums = [w['window_num'] for w in successful_windows]
    profits = [w['test_profit_pct'] for w in successful_windows]
    win_rates = [w['test_win_rate'] for w in successful_windows]
    trades_counts = [w['test_trades'] for w in successful_windows]
    sharpe_ratios = [w['test_sharpe'] for w in successful_windows]
    
    if not successful_windows:
        print("⚠️  Нет успешных окон для построения графиков.")
        return
    
    # Создаем мульти-график
    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle(f'📊 Walk-Forward Analysis: {strategy_name}', fontsize=16, fontweight='bold')
    
    # 1. Прибыль по окнам
    colors = ['green' if p > 0 else 'red' for p in profits]
    bars1 = ax1.bar(window_nums, profits, color=colors, alpha=0.7, edgecolor='black')
    ax1.axhline(y=0, color='black', linestyle='-', alpha=0.3)
    ax1.set_title('💰 Прибыль по окнам (%)', fontweight='bold')
    ax1.set_xlabel('Номер окна')
    ax1.set_ylabel('Прибыль (%)')
    ax1.grid(True, alpha=0.3)
    
    # Добавляем подписи на столбцы
    for bar, profit in zip(bars1, profits):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height + (0.1 if height > 0 else -0.3),
                f'{profit:.1f}%', ha='center', va='bottom' if height > 0 else 'top', fontsize=9)
    
    # 2. Win Rate по окнам
    ax2.plot(window_nums, win_rates, 'o-', color='blue', linewidth=2, markersize=6)
    ax2.axhline(y=50, color='gray', linestyle='--', alpha=0.5, label='50%')
    ax2.set_title('🎯 Win Rate по окнам', fontweight='bold')
    ax2.set_xlabel('Номер окна')
    ax2.set_ylabel('Win Rate (%)')
    ax2.set_ylim(0, 100)
    ax2.grid(True, alpha=0.3)
    ax2.legend()
    
    # 3. Количество сделок
    ax3.bar(window_nums, trades_counts, color='orange', alpha=0.7, edgecolor='black')
    ax3.set_title('📊 Количество сделок', fontweight='bold')
    ax3.set_xlabel('Номер окна')
    ax3.set_ylabel('Количество сделок')
    ax3.grid(True, alpha=0.3)
    
    # 4. Sharpe Ratio
    ax4.plot(window_nums, sharpe_ratios, 's-', color='purple', linewidth=2, markersize=6)
    ax4.axhline(y=1.0, color='gray', linestyle='--', alpha=0.5, label='Sharpe = 1.0')
    ax4.axhline(y=2.0, color='green', linestyle='--', alpha=0.5, label='Sharpe = 2.0')
    ax4.set_title('📈 Sharpe Ratio по окнам', fontweight='bold')
    ax4.set_xlabel('Номер окна')
    ax4.set_ylabel('Sharpe Ratio')
    ax4.grid(True, alpha=0.3)
    ax4.legend()
    
    plt.tight_layout()
    
    # Сохраняем график
    timestamp = int(time.time())
    filename = f"WalkForward_{strategy_name}_{timestamp}.png"
    filepath = charts_dir / filename
    
    plt.savefig(filepath, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✨ График сохранен: {filepath}")
    plt.close()


def print_detailed_summary(walk_forward_results: dict) -> None:
    """
    Выводит детальную сводку по всем окнам.
    """
    windows = walk_forward_results['windows']
    
    print("\n" + "="*80)
    print("📋 ДЕТАЛЬНАЯ СВОДКА ПО ОКНАМ")
    print("="*80)
    
    successful_count = 0
    profitable_count = 0
    total_profit = 0
    total_trades = 0
    
    for window in windows:
        print(f"\n🗓️  ОКНО {window['window_num']}:")
        print(f"   📅 Обучение: {window['train_period']}")
        print(f"   🔍 Тест: {window['test_period']}")
        print(f"   ⚙️  Лучшие параметры: {window['best_params']}")
        print(f"   🎯 Оценка оптимизации: {window['optimization_score']:.4f}")
        
        if window['success']:
            successful_count += 1
            total_profit += window['test_profit_pct']
            total_trades += window['test_trades']
            
            if window['test_profit_pct'] > 0:
                profitable_count += 1
                status = "✅ ПРИБЫЛЬ"
            else:
                status = "❌ УБЫТОК"
            
            print(f"   💰 Результат: {status} {window['test_profit_pct']:+.2f}%")
            print(f"   📊 Сделок: {window['test_trades']} | Win Rate: {window['test_win_rate']:.1f}%")
            print(f"   📈 Sharpe: {window['test_sharpe']:.3f} | Sortino: {window['test_sortino']:.3f}")
            print(f"   📉 Max Drawdown: {window['test_max_drawdown']:.2f}%")
        else:
            error_msg = window.get('error', 'Неизвестная ошибка')
            print(f"   ❌ ПРОВАЛ: {error_msg}")
    
    print(f"\n" + "-"*80)
    print(f"📊 ОБЩАЯ СТАТИСТИКА:")
    print(f"   ✅ Успешных окон: {successful_count}/{len(windows)} ({successful_count/len(windows)*100:.1f}%)")
    print(f"   💰 Прибыльных окон: {profitable_count}/{successful_count} ({profitable_count/successful_count*100:.1f}% от успешных)" if successful_count > 0 else "   💰 Прибыльных окон: 0")
    print(f"   💵 Средняя прибыль: {total_profit/successful_count:.2f}%" if successful_count > 0 else "   💵 Средняя прибыль: N/A")
    print(f"   🔄 Всего сделок: {total_trades}")


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
    train_window_days = train_window_months * 30 * 24
    test_window_days = test_window_months * 30 * 24
    step_days = step_months * 30 * 24
    
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
    
    # Общий прогресс-бар для всех окон
    total_iterations = window_count * n_trials_per_window
    overall_start = time.time()
    
    print("\n" + "-"*80)
    print(f"⏰ Предполагаемое время выполнения: {total_iterations * 0.5 / 60:.1f} минут")
    print("-"*80)
    
    # ==================================================================
    # 🔄 ОСНОВНОЙ ЦИКЛ: ПО КАЖДОМУ ОКНУ
    # ==================================================================
    
    start_idx = 0
    
    for window_num in range(1, window_count + 1):
        window_start_time = time.time()
        
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
        
        # Оптимизируем с прогресс-баром
        optimization_start = time.time()
        
        with tqdm(total=n_trials_per_window, desc=f"      🔍 Окно {window_num}", leave=False, ncols=80) as pbar:
            def callback(study, trial):
                pbar.update(1)
                if trial.value is not None:
                    pbar.set_postfix({
                        'Best': f'{study.best_value:.3f}',
                        'Current': f'{trial.value:.3f}'
                    })
            
            study.optimize(
                lambda trial: objective_function(trial, train_data, opt_config_path), 
                n_trials=n_trials_per_window,
                callbacks=[callback]
            )
        
        optimization_time = time.time() - optimization_start
        print(f"   ⏱️  Время оптимизации: {optimization_time:.1f}с")
        
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
        
        window_time = time.time() - window_start_time
        remaining_windows = window_count - window_num
        estimated_remaining = remaining_windows * window_time
        
        print(f"   ✅ Окно {window_num} завершено за {window_time:.1f}с!")
        if remaining_windows > 0:
            print(f"   ⏳ Осталось окон: {remaining_windows} (~{estimated_remaining/60:.1f} мин)")
    
    total_time = time.time() - overall_start
    print(f"\n🎉 ВСЕ ОКНА ЗАВЕРШЕНЫ ЗА {total_time/60:.1f} МИНУТ!")
    
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
    volatility_penalty = min(float(profit_cv), 100.0)  # Явное приведение к float
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

    print(f"\n🚀 ЗАПУСК WALK-FORWARD ANALYSIS")
    print(f"🎯 Стратегия: {strategy_name}")
    print(f"🔥 Итераций на окно: {args.trials}")
    
    start_time = time.time()
    
    # Запускаем walk-forward analysis
    walk_forward_results = run_walk_forward_optimization(
        all_data=all_data, 
        opt_config_path=args.config, 
        n_trials_per_window=args.trials
    )
    
    total_time = time.time() - start_time
    
    # Выводим детальную сводку
    print_detailed_summary(walk_forward_results)
    
    # Генерируем графики
    print(f"\n🎨 Генерируем аналитические графики...")
    generate_walk_forward_charts(walk_forward_results, strategy_name)
    
    # Анализируем переобучение
    overfitting_analysis = analyze_overfitting(walk_forward_results)
    
    print(f"\n🎉 WALK-FORWARD ANALYSIS ЗАВЕРШЕН!")
    print(f"⏱️  Общее время выполнения: {total_time/60:.1f} мин")
    print(f"📁 Результаты сохранены в папке charts/")