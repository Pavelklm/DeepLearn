# Файл: trading/optimizer_utils.py

import matplotlib.pyplot as plt
import seaborn as sns
import time
from pathlib import Path
import numpy as np

CHARTS_DIR = Path('charts')
CHARTS_DIR.mkdir(exist_ok=True)

# ---------------------------------------
# Печать детальной сводки по окнам
# ---------------------------------------
def print_detailed_summary(walk_forward_results: dict) -> None:
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
        print(f"   🎯 Обучение: {window['train_period']}")
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

    print("\n" + "-"*80)
    print(f"📊 ОБЩАЯ СТАТИСТИКА:")
    print(f"   ✅ Успешных окон: {successful_count}/{len(windows)} ({successful_count/len(windows)*100:.1f}%)")
    print(f"   💰 Прибыльных окон: {profitable_count}/{successful_count} ({profitable_count/successful_count*100:.1f}% от успешных)" if successful_count else "   💰 Прибыльных окон: 0")
    print(f"   💵 Средняя прибыль: {total_profit/successful_count:.2f}%" if successful_count else "   💵 Средняя прибыль: N/A")
    print(f"   🔄 Всего сделок: {total_trades}")


# ---------------------------------------
# Генерация графиков walk-forward
# ---------------------------------------
def generate_walk_forward_charts(walk_forward_results: dict, strategy_name: str) -> None:
    windows = walk_forward_results['windows']
    successful_windows = [w for w in windows if w['success']]
    if not successful_windows:
        print("⚠️ Нет успешных окон для графиков.")
        return

    window_nums = [w['window_num'] for w in successful_windows]
    profits = [w['test_profit_pct'] for w in successful_windows]
    win_rates = [w['test_win_rate'] for w in successful_windows]
    trades_counts = [w['test_trades'] for w in successful_windows]
    sharpe_ratios = [w['test_sharpe'] for w in successful_windows]

    fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
    fig.suptitle(f'📊 Walk-Forward Analysis: {strategy_name}', fontsize=16, fontweight='bold')

    # Прибыль
    colors = ['green' if p > 0 else 'red' for p in profits]
    bars = ax1.bar(window_nums, profits, color=colors, alpha=0.7, edgecolor='black')
    ax1.axhline(0, color='black', alpha=0.3)
    ax1.set_title('💰 Прибыль по окнам (%)', fontweight='bold')
    ax1.set_xlabel('Номер окна'); ax1.set_ylabel('Прибыль (%)')
    for bar, p in zip(bars, profits):
        h = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., h + (0.1 if h > 0 else -0.3),
                 f'{p:.1f}%', ha='center', va='bottom' if h > 0 else 'top', fontsize=9)
    ax1.grid(True, alpha=0.3)

    # Win Rate
    ax2.plot(window_nums, win_rates, 'o-', color='blue', linewidth=2, markersize=6)
    ax2.axhline(50, color='gray', linestyle='--', alpha=0.5)
    ax2.set_title('🎯 Win Rate по окнам', fontweight='bold')
    ax2.set_xlabel('Номер окна'); ax2.set_ylabel('Win Rate (%)'); ax2.set_ylim(0, 100)
    ax2.grid(True, alpha=0.3)

    # Количество сделок
    ax3.bar(window_nums, trades_counts, color='orange', alpha=0.7, edgecolor='black')
    ax3.set_title('📊 Количество сделок', fontweight='bold')
    ax3.set_xlabel('Номер окна'); ax3.set_ylabel('Сделок'); ax3.grid(True, alpha=0.3)

    # Sharpe Ratio
    ax4.plot(window_nums, sharpe_ratios, 's-', color='purple', linewidth=2, markersize=6)
    ax4.axhline(1.0, color='gray', linestyle='--', alpha=0.5, label='Sharpe=1.0')
    ax4.axhline(2.0, color='green', linestyle='--', alpha=0.5, label='Sharpe=2.0')
    ax4.set_title('📈 Sharpe Ratio по окнам', fontweight='bold')
    ax4.set_xlabel('Номер окна'); ax4.set_ylabel('Sharpe Ratio'); ax4.grid(True, alpha=0.3)
    ax4.legend()

    plt.tight_layout()
    filename = CHARTS_DIR / f"WalkForward_{strategy_name}_{int(time.time())}.png"
    plt.savefig(filename, dpi=300, bbox_inches='tight', facecolor='white')
    print(f"✨ График сохранен: {filename}")
    plt.close()


# ---------------------------------------
# Анализ переобучения
# ---------------------------------------
def analyze_overfitting(walk_forward_results: dict) -> dict:
    windows = walk_forward_results['windows']
    profits = [w['test_profit_pct'] for w in windows if w['success']]
    total_windows = len(windows)
    successful_windows = len(profits)

    if successful_windows == 0:
        return {'overfitting_score': 100, 'verdict': 'КРИТИЧЕСКИЙ ПРОВАЛ'}

    mean_profit = np.mean(profits)
    std_profit = np.std(profits)
    profit_cv = (std_profit / abs(mean_profit) * 100) if mean_profit != 0 else 999
    profitable_windows = sum(1 for p in profits if p > 0)
    profit_consistency = profitable_windows / successful_windows * 100

    losing_penalty = (total_windows - profitable_windows) / total_windows * 100
    volatility_penalty = min(float(profit_cv), 100)
    consistency_penalty = 100 - profit_consistency

    overfitting_score = losing_penalty*0.4 + volatility_penalty*0.4 + consistency_penalty*0.2

    if overfitting_score < 20:
        verdict = "🟢 Отличная стратегия"
        recommendation = "Стабильна во времени."
    elif overfitting_score < 40:
        verdict = "🟡 Приемлемая стратегия"
        recommendation = "Требует осторожности."
    elif overfitting_score < 70:
        verdict = "🟠 Сомнительная стратегия"
        recommendation = "Признаки переобучения."
    else:
        verdict = "🔴 Плохая стратегия"
        recommendation = "Нужен пересмотр подхода."

    print(f"\n🎯 Overfitting Score: {overfitting_score:.1f}% → {verdict}")
    print(f"💡 Рекомендация: {recommendation}")

    return {
        'overfitting_score': overfitting_score,
        'verdict': verdict,
        'mean_profit': mean_profit,
        'profit_cv': profit_cv,
        'profit_consistency': profit_consistency,
        'recommendation': recommendation,
        'successful_windows': successful_windows,
        'total_windows': total_windows
    }


# ---------------------------------------
# Бэктест чемпиона
# ---------------------------------------
def run_champion_backtest(best_params, strategy_name, all_data, opt_config_path):
    import json
    from bot_process import Playground
    print("\n" + "="*80)
    print(f"🏆 БЭКТЕСТ ЛУЧШЕЙ СТРАТЕГИИ: {strategy_name}")
    print("="*80)

    with open(opt_config_path, 'r', encoding='utf-8') as f:
        opt_config = json.load(f)

    test_cfg = {
        "bot_name": f"Champion_{strategy_name}_FullBacktest",
        "strategy_file": opt_config["strategy_file"],
        "risk_config_file": "configs/live_default.json",
        "strategy_params": best_params,
        "generate_chart": True
    }

    try:
        backtest = Playground(test_cfg, test_cfg['bot_name'], all_data)
        backtest.run()
        print("🎉 Бэктест чемпиона завершен. Отчеты и графики в charts/")
    except Exception as e:
        print(f"❌ Ошибка при бэктесте чемпиона: {e}")
