# Файл: trading/reporting/backtest_reporter.py

import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from risk_management.performance_tracker import PerformanceTracker
from analytics.metrics_calculator import MetricsCalculator


class BacktestReporter:
    """
    Создает визуальные и текстовые отчеты по результатам бэктеста.
    """
    def __init__(self, bot_name: str, tracker: PerformanceTracker, initial_balance: float):
        self.bot_name = bot_name
        self.tracker = tracker
        self.initial_balance = initial_balance

        sns.set_theme(style="darkgrid")

    def generate_report(self, ohlcv_data: pd.DataFrame, save_path: str = "charts"):
        """
        Генерирует полный отчет: текст + график сделок.
        """
        trade_history_dicts = [t.__dict__ for t in self.tracker.trade_history]

        if not trade_history_dicts:
            print(f"Отчет для '{self.bot_name}': Нет сделок для анализа.")
            return

        report_text = self._generate_text_summary(trade_history_dicts)
        print(report_text)
        self._generate_trade_chart(ohlcv_data, trade_history_dicts, save_path)

    def _generate_text_summary(self, trade_history_dicts: list) -> str:
        """
        Создает текстовую сводку с ключевыми метриками производительности.
        """
        metrics_calculator = MetricsCalculator(trade_history_dicts, self.initial_balance)
        metrics = metrics_calculator.calculate_all_metrics()

        summary = self.tracker.get_statistics_summary()

        total_return_pct = metrics.total_return_pct
        final_balance = self.initial_balance * (1 + metrics.total_return_pct / 100)
        max_drawdown_pct = metrics.max_drawdown_pct

        report = f"""
        ============================================================
        📊 ОТЧЕТ ПО БЭКТЕСТУ: {self.bot_name}
        ============================================================

        ОСНОВНЫЕ ПОКАЗАТЕЛИ:
        -------------------
        - Общая прибыль: ${summary.get('total_profit', 0):.2f}
        - Общая доходность: {total_return_pct:.2f}%
        - Начальный баланс: ${self.initial_balance:.2f}
        - Конечный баланс: ${final_balance:.2f}

        СТАТИСТИКА СДЕЛОК:
        ------------------
        - Всего сделок: {summary.get('total_trades', 0)}
        - Прибыльные сделки: {summary.get('winning_trades', 0)}
        - Убыточные сделки: {summary.get('losing_trades', 0)}
        - Винрейт (Win Rate): {summary.get('winrate', 0) * 100:.2f}%

        МЕТРИКИ РИСКА И ЭФФЕКТИВНОСТИ:
        -------------------------------
        - Максимальная просадка: {max_drawdown_pct:.2f}%
        - Коэффициент Шарпа: {metrics.sharpe_ratio:.4f}
        - Коэффициент Сортино: {metrics.sortino_ratio:.4f}
        - Коэффициент Кальмара: {metrics.calmar_ratio:.4f}

        ============================================================
        """
        return report

    def _generate_trade_chart(self, ohlcv_data: pd.DataFrame, trade_history_dicts: list, save_path_str: str):
        """
        Создает и сохраняет график цены с отметками входов/выходов и соединяющими линиями.
        """
        df_trades = pd.DataFrame(trade_history_dicts)
        if df_trades.empty:
            return

        df_trades['timestamp'] = pd.to_datetime(df_trades['timestamp'])
        df_trades['entry_timestamp'] = pd.to_datetime(df_trades['entry_timestamp'])

        plt.figure(figsize=(20, 10))

        # === График цены ===
        plt.plot(ohlcv_data.index, ohlcv_data['Close'],
                 label='Цена Close', color='lightblue', alpha=0.7)

        # Метки входов
        plt.plot(df_trades['entry_timestamp'], df_trades['entry_price'],
                 '^', markersize=8, color='blue', label='Вход')

        # Выходы + соединительные линии
        for i, trade in df_trades.iterrows():
            entry_time = trade['entry_timestamp']
            exit_time = trade['timestamp']
            entry_price = trade['entry_price']
            exit_price = trade['exit_price']

            color = 'green' if trade['success'] else 'red'

            # точка выхода
            plt.plot(exit_time, exit_price, 'o', markersize=8,
                     color=color, label='Выход' if i == 0 else "")

            # соединяющая линия (вход → выход)
            plt.plot([entry_time, exit_time],
                     [entry_price, exit_price],
                     color=color, linewidth=2, alpha=0.8)

        # === Оформление ===
        plt.title(f'Результаты бэктеста для: {self.bot_name}')
        plt.xlabel('Дата')
        plt.ylabel('Цена (USD)')
        plt.legend(loc='upper left', framealpha=0.9)
        plt.xticks(rotation=45)
        plt.tight_layout()

        save_path = Path(save_path_str)
        save_path.mkdir(parents=True, exist_ok=True)
        chart_file = save_path / f"{self.bot_name}.png"
        plt.savefig(chart_file)
        plt.close()
        print(f"📈 График сохранен в: {chart_file}")
