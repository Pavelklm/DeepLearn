import json
import logging
import time
import argparse
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
import pandas as pd
import yfinance as yf
from tqdm import tqdm
import optuna
import sys

# --- Улучшенный и более надежный блок импорта ---
# Используем проверку __package__, чтобы явно определить, как запущен скрипт.
# Это более надежный способ для статических анализаторов, чем try/except ImportError.
try:
    if __package__:
        # Скрипт запущен как часть пакета (например, 'python -m optimizer.main_optimizer').
        # Используем относительные импорты.
        from .objective_function import OptimizerObjective
        from .validation_engine import ValidationEngine
        from .statistical_tests import StatisticalValidator
        from .utils import OptimizerUtils, OptimizerReporter
    else:
        # Скрипт запущен напрямую. Добавляем родительскую директорию в path.
        current_dir = Path(__file__).parent
        if str(current_dir) not in sys.path:
            sys.path.insert(0, str(current_dir))
        
        from objective_function import OptimizerObjective
        from validation_engine import ValidationEngine
        from statistical_tests import StatisticalValidator
        from utils import OptimizerUtils, OptimizerReporter

except ImportError as e:
    # Этот блок сработает, только если файлы действительно отсутствуют
    logging.basicConfig(level=logging.CRITICAL, format="%(asctime)s - %(levelname)s - %(message)s")
    logging.critical(f"Критическая ошибка: не удалось импортировать модуль. {e}")
    logging.critical("Убедитесь, что все необходимые файлы ('objective_function.py', 'utils.py' и др.) "
                     "находятся в той же директории, что и 'main_optimizer.py'.")
    sys.exit(1)

# ------------------------------------


class AdvancedOptimizer:
    """Продвинутая система оптимизации торговых стратегий с защитой от overfitting."""

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or str(Path(__file__).parent / "optimizer_config.json")
        self.config: Dict[str, Any] = self._load_config()
        self._setup_logging()
        self._setup_directories()

        self.objective = OptimizerObjective(self.config)
        self.validator = ValidationEngine(self.config)
        self.statistical = StatisticalValidator(self.config)
        self.utils = OptimizerUtils(self.config)
        self.reporter = OptimizerReporter(self.config)

        self.results: Dict[str, Any] = {}
        self.overfitting_warnings: List[str] = []
        
        # Для отслеживания прогресса
        self.start_time = None
        self.window_times = []

    def _load_config(self) -> Dict[str, Any]:
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Конфиг не найден: {self.config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Ошибка в JSON конфиге: {e}")

    def _setup_logging(self):
        log_config = self.config.get("logging", {})
        level_str = log_config.get("level", "INFO").upper()
        level = getattr(logging, level_str, logging.INFO)

        handlers = [logging.StreamHandler(sys.stdout)]
        if log_config.get("save_to_file"):
            log_file = Path(__file__).parent / log_config.get("log_file", "optimizer.log")
            handlers.append(logging.FileHandler(log_file, encoding='utf-8'))

        logging.basicConfig(
            level=level,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            handlers=handlers,
            force=True
        )
        self.logger = logging.getLogger(__name__)
        
        if isinstance(handlers[0], logging.StreamHandler) and hasattr(handlers[0].stream, 'reconfigure'):
             try:
                handlers[0].stream.reconfigure(encoding='utf-8')
             except TypeError:
                pass

        # Минимальное логирование для красивого вывода
        optuna.logging.set_verbosity(optuna.logging.ERROR)
        
        # Отключаем все лишние логи
        logging.getLogger("risk_management.performance_tracker").setLevel(logging.ERROR)
        logging.getLogger("risk_management.telegram_notifier").setLevel(logging.ERROR)
        logging.getLogger("bot_process").setLevel(logging.ERROR)
        logging.getLogger("yfinance").setLevel(logging.ERROR)
        logging.getLogger("urllib3.connectionpool").setLevel(logging.ERROR)
        logging.getLogger("matplotlib").setLevel(logging.ERROR)
        logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)
        logging.getLogger("PIL").setLevel(logging.ERROR)

    def _setup_directories(self):
        charts_dir = Path(self.config.get("reporting", {}).get("charts_directory", "./charts"))
        charts_dir.mkdir(parents=True, exist_ok=True)
    
    def _format_time(self, seconds: float) -> str:
        """Красивое форматирование времени."""
        if seconds < 60:
            return f"{seconds:.1f}с"
        elif seconds < 3600:
            return f"{seconds/60:.1f}м"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}ч {minutes}м"
    
    def _estimate_eta(self, completed: int, total: int, elapsed: float) -> str:
        """Оценка оставшегося времени."""
        if completed == 0:
            return "~"
        
        avg_time_per_window = elapsed / completed
        remaining = total - completed
        eta_seconds = avg_time_per_window * remaining
        
        return self._format_time(eta_seconds)
    
    def _print_window_summary(self, window_result: Dict, window_num: int, total_windows: int, elapsed: float):
        """Красивый вывод статистики по окну."""
        success = "[+]" if window_result.get('success', False) else "[-]"
        test_score = window_result.get('test_score', 0)
        trades = window_result.get('test_trades', 0)
        eta = self._estimate_eta(window_num, total_windows, elapsed)
        progress = window_num / total_windows * 100
        
        # Профит из метрик
        profit_pct = 0.0
        sharpe = 0.0
        if window_result.get('test_metrics'):
            metrics = window_result['test_metrics']
            if hasattr(metrics, 'total_return_pct'):
                profit_pct = metrics.total_return_pct
            if hasattr(metrics, 'sharpe_ratio'):
                sharpe = metrics.sharpe_ratio
        
        print(f"\n{success} Окно {window_num:2d}/{total_windows} [{progress:5.1f}%] | "
              f"Оценка: {test_score:6.3f} | Сделок: {trades:3d} | "
              f"Профит: {profit_pct:+6.2f}% | Sharpe: {sharpe:5.2f} | "
              f"Прошло: {self._format_time(elapsed)} | ETA: {eta}")
        
        # Лучшие параметры для успешных окон
        if window_result.get('success', False) and window_result.get('best_params'):
            params = window_result['best_params']
            params_str = ', '.join([f"{k}={v:.2f}" if isinstance(v, float) else f"{k}={v}" for k, v in params.items()])
            print(f"    ✓ Лучшие параметры: {params_str[:80]}{'...' if len(params_str) > 80 else ''}")
        
        if not window_result.get('success', False):
            # Показываем причину ошибки
            rejections = window_result.get('rejection_summary', {})
            if rejections:
                top_reason = max(rejections.items(), key=lambda x: x[1])
                print(f"    ⚠️  Осн. проблема: {top_reason[0]} ({top_reason[1]}/{sum(rejections.values())} попыток)")

    def load_data(
        self,
        ticker: Optional[str] = None,
        period: Optional[str] = None,
        interval: Optional[str] = None,
    ) -> pd.DataFrame:
        data_config = self.config.get("data_settings", {})
        ticker = ticker or data_config.get("default_ticker", "AAPL")
        period = period or data_config.get("default_period", "1y")
        interval = interval or data_config.get("default_interval", "1d")

        print(f"📈 Загрузка данных: {ticker} | {period} | {interval}")
        df = yf.download(tickers=ticker, period=period, interval=interval, auto_adjust=True, progress=False)

        if df is None or df.empty:
            raise ValueError(f"Не удалось загрузить данные для {ticker}")

        min_points = data_config.get("min_data_points", 100)
        if len(df) < min_points:
            raise ValueError(f"Недостаточно данных: {len(df)} < {min_points}")

        print(f"✅ Данные загружены: {len(df)} свечей ({df.index[0].date()} - {df.index[-1].date()})")
        return df

    def create_data_splits(self, data: pd.DataFrame) -> List[Dict[str, Any]]:
        wf_config = self.config.get("walk_forward", {})

        def get_offset(months_value):
            if isinstance(months_value, float):
                return pd.DateOffset(days=int(months_value * 30.44))
            return pd.DateOffset(months=int(months_value))

        train_offset = get_offset(wf_config.get("train_months", 6))
        val_offset = get_offset(wf_config.get("validation_months", 3))
        test_offset = get_offset(wf_config.get("test_months", 3))
        step_offset = get_offset(wf_config.get("step_months", 1))

        start_date = data.index[0]
        end_date = data.index[-1]
        windows = []
        current_start = start_date

        while True:
            train_end = current_start + train_offset
            val_end = train_end + val_offset
            test_end = val_end + test_offset
            if test_end > end_date:
                break

            window = {
                "window_id": len(windows) + 1,
                "train_start": current_start, "train_end": train_end,
                "val_start": train_end, "val_end": val_end,
                "test_start": val_end, "test_end": test_end,
                "train_data": data.loc[current_start:train_end],
                "val_data": data.loc[train_end:val_end],
                "test_data": data.loc[val_end:test_end],
            }
            windows.append(window)
            current_start += step_offset
            if len(windows) >= wf_config.get("max_windows", 12):
                break

        if not windows or len(windows) < wf_config.get("min_windows", 1):
            raise ValueError(f"Недостаточно данных для walk-forward: создано {len(windows)} окон, "
                             f"требуется минимум {wf_config.get('min_windows', 1)}")
        return windows

    def optimize_single_window(self, window: Dict[str, Any], strategy_config_path: str) -> Dict[str, Any]:
        window_id = window["window_id"]
        opt_config = self.config.get("optimization", {})
        window_start_time = time.time()

        study = optuna.create_study(direction=opt_config.get("study_direction", "maximize"))
        objective_func = lambda trial: self.objective.evaluate(trial, window["train_data"], strategy_config_path, mode="train")

        # Оптимизация без лишних логов
        study.optimize(
            objective_func, 
            n_trials=opt_config.get("trials_per_window", 50),
            timeout=opt_config.get("timeout_minutes", 10) * 60,
            n_jobs=opt_config.get("n_jobs", 1)
        )

        # FIX: Собираем статистику по причинам отклонения trials
        rejection_reasons = [t.user_attrs.get('rejection_reason', 'Accepted') for t in study.trials]
        rejection_summary = Counter(reason for reason in rejection_reasons if reason != 'Accepted')

        if not study.best_trial:
             raise RuntimeError("Optuna не нашла лучшего испытания. Возможно, все испытания завершились с ошибкой.")

        best_params = study.best_trial.params
        train_score = study.best_trial.value

        val_result = self.objective.evaluate_fixed_params(best_params, window["val_data"], strategy_config_path, mode="validation")
        val_score = val_result.get("score", 0.0)
        test_result = self.objective.evaluate_fixed_params(best_params, window["test_data"], strategy_config_path, mode="test")
        test_score = test_result.get("score", 0.0)

        overfitting_detected = True if train_score is None else self.validator.detect_overfitting(train_score, val_score, test_score)
        statistical_valid = self.statistical.validate_trades(test_result.get("trades", [])) if test_result.get("trades") else False

        window_result = {
            "window_id": window_id,
            "train_period": f"{window['train_start'].date()} → {window['train_end'].date()}",
            "val_period": f"{window['val_start'].date()} → {window['val_end'].date()}",
            "test_period": f"{window['test_start'].date()} → {window['test_end'].date()}",
            "best_params": best_params,
            "train_score": train_score, "val_score": val_score, "test_score": test_score,
            "test_metrics": test_result.get("metrics", {}),
            "test_trades": len(test_result.get("trades", [])),
            "overfitting_detected": overfitting_detected,
            "statistical_valid": statistical_valid,
            "success": test_score > self.config.get("validation", {}).get("min_test_score", 0) and not overfitting_detected and statistical_valid,
            "rejection_summary": rejection_summary,
        }
        return window_result

    def run_walk_forward_optimization(self, data: pd.DataFrame, strategy_config_path: str) -> Dict[str, Any]:
        print("\n" + "="*80)
        print("🚀 WALK-FORWARD ОПТИМИЗАЦИЯ STARTED")
        print("="*80)
        
        self.start_time = time.time()
        windows = self.create_data_splits(data)
        window_results = []
        
        strategy_name = Path(strategy_config_path).stem
        print(f"📊 Стратегия: {strategy_name}")
        print(f"📅 Окон: {len(windows)} | Период: {data.index[0].date()} - {data.index[-1].date()}")
        print(f"📝 Данных: {len(data)} свечей | Trials/окно: {self.config.get('optimization', {}).get('trials_per_window', 50)}")
        print("-" * 80)

        for i, window in enumerate(windows, 1):
            window_start_time = time.time()  # Время начала окна
            try:
                result = self.optimize_single_window(window, strategy_config_path)
                window_results.append(result)
                
                # Красивый вывод статистики
                elapsed = time.time() - self.start_time
                self._print_window_summary(result, i, len(windows), elapsed)
                
                # Сохраняем время окна для статистики
                window_time = time.time() - window_start_time
                self.window_times.append(window_time)
                
            except Exception as e:
                error_result = {"window_id": window.get("window_id", -1), "success": False, "error": str(e)}
                window_results.append(error_result)
                
                elapsed = time.time() - self.start_time
                self._print_window_summary(error_result, i, len(windows), elapsed)
                print(f"    >> Критическая ошибка: {str(e)[:100]}...")
                
                # Сохраняем время окна даже при ошибке
                window_time = time.time() - window_start_time
                self.window_times.append(window_time)

        analysis = self.validator.analyze_walk_forward_results(window_results)
        best_params = self.utils.find_robust_parameters(window_results)

        final_backtest = None
        if best_params:
            print("\n" + "-"*80)
            print("🏆 Запуск финального бэктеста...")
            final_backtest = self.objective.evaluate_fixed_params(best_params, data, strategy_config_path, mode="final")
        else:
            print("\n" + "-"*80)
            print("⚠️  Нет робастных параметров для финального бэктеста")

        duration = time.time() - self.start_time
        
        # FIX: Агрегируем статистику по причинам отклонений со всех окон
        total_rejections = Counter()
        for res in window_results:
            if res.get("rejection_summary"):
                total_rejections.update(res["rejection_summary"])

        results = {
            "strategy_config": strategy_config_path,
            "total_windows": len(windows),
            "successful_windows": len([w for w in window_results if w.get("success")]),
            "window_results": window_results,
            "analysis": analysis,
            "best_parameters": best_params,
            "final_backtest": final_backtest,
            "execution_time_minutes": duration / 60,
            "overfitting_warnings": analysis.get("warnings", []),
            "timestamp": datetime.now().isoformat(),
            "total_rejection_summary": total_rejections,
        }

        self.results = results
        
        # Генерация отчетов без логов
        print("\n📈 Генерация отчетов...")
        self.reporter.generate_full_report(results, data)
        
        # Красивый вывод финальной статистики
        self._print_final_summary(results)
        
        print(f"\n🎉 ОПТИМИЗАЦИЯ ЗАВЕРШЕНА за {self._format_time(duration)}")
        return results
    
    def _print_final_summary(self, results: Dict):
        """Красивый вывод финальной статистики."""
        print("\n" + "="*80)
        print("📊 ФИНАЛЬНАЯ СТАТИСТИКА")
        print("="*80)
        
        strategy_name = Path(results['strategy_config']).stem
        successful_windows = results['successful_windows']
        total_windows = results['total_windows']
        success_rate = (successful_windows / total_windows * 100) if total_windows > 0 else 0
        
        print(f"📝 Стратегия: {strategy_name}")
        print(f"⏱️  Время выполнения: {self._format_time(results['execution_time_minutes'] * 60)}")
        print(f"🗺️  Дата: {results['timestamp'][:19].replace('T', ' ')}")
        
        # Статистика по скорости
        if hasattr(self, 'window_times') and self.window_times:
            avg_window_time = sum(self.window_times) / len(self.window_times)
            print(f"⏱️  Ср. время/окно: {self._format_time(avg_window_time)}")
        
        print(f"\n📊 ОКНА:")
        print(f"   ✅ Успешно: {successful_windows}/{total_windows} ({success_rate:.1f}%)")
        
        if successful_windows > 0:
            # Статистика по успешным окнам
            successful_results = [w for w in results['window_results'] if w.get('success', False)]
            
            test_scores = [w.get('test_score', 0) for w in successful_results]
            trade_counts = [w.get('test_trades', 0) for w in successful_results]
            
            profits = []
            for w in successful_results:
                if w.get('test_metrics') and hasattr(w['test_metrics'], 'total_return_pct'):
                    profits.append(w['test_metrics'].total_return_pct)
                else:
                    profits.append(0.0)
            
            print(f"   💯 Ср. оценка: {sum(test_scores)/len(test_scores):.3f}")
            print(f"   📋 Ср. сделок: {sum(trade_counts)/len(trade_counts):.1f}")
            print(f"   💰 Ср. профит: {sum(profits)/len(profits):+.2f}%")
            print(f"   🔄 Макс. профит: {max(profits):+.2f}% | Мин.: {min(profits):+.2f}%")
            
            # Оверфиттинг скор
            analysis = results.get('analysis', {})
            if analysis and analysis.get('status') != 'insufficient_data':
                overfitting_score = analysis.get('overfitting_score', 0)
                print(f"\n🎯 OVERFITTING SCORE: {overfitting_score:.1f}/100")
                if overfitting_score < 40:
                    verdict = "🟢 Низкий риск"
                elif overfitting_score < 70:
                    verdict = "🟡 Умеренный риск"
                else:
                    verdict = "🔴 Высокий риск"
                print(f"   {verdict}")
            
            # Лучшие параметры
            best_params = results.get('best_parameters')
            if best_params:
                print(f"\n🏆 ЛУЧШИЕ ПАРАМЕТРЫ:")
                for param, value in best_params.items():
                    if isinstance(value, float):
                        print(f"   {param}: {value:.3f}")
                    else:
                        print(f"   {param}: {value}")
            
            # Финальный бэктест
            final_backtest = results.get('final_backtest')
            if final_backtest and final_backtest.get('success'):
                metrics = final_backtest.get('metrics')
                if metrics:
                    print(f"\n📈 ФИНАЛЬНЫЙ БЭКТЕСТ:")
                    print(f"   💰 Общая доходность: {metrics.total_return_pct:+.2f}%")
                    print(f"   📉 Sharpe Ratio: {metrics.sharpe_ratio:.3f}")
                    print(f"   📉 Sortino Ratio: {metrics.sortino_ratio:.3f}")
                    print(f"   📊 Max Drawdown: {metrics.max_drawdown_pct:.2f}%")
        
        else:
            # Диагностика проблем
            rejections = results.get('total_rejection_summary')
            if rejections:
                total_failed_trials = sum(rejections.values())
                print(f"\n⚠️  ДИАГНОСТИКА ПРОБЛЕМ ({total_failed_trials} неудачных попыток):")
                for reason, count in rejections.most_common(5):  # Топ-5 проблем
                    percentage = (count / total_failed_trials) * 100
                    print(f"   {percentage:5.1f}% - {reason}")
                
                print(f"\n💡 РЕКОМЕНДАЦИИ:")
                print(f"   • Проверьте логику стратегии (слишком мало сделок)")
                print(f"   • Расширьте диапазоны параметров в конфиге стратегии")
                print(f"   • Снизьте min_trades_for_significance в optimizer_config.json")
        
        # Предупреждения
        warnings = results.get('overfitting_warnings', [])
        if warnings:
            print(f"\n⚠️  ПРЕДУПРЕЖДЕНИЯ:")
            for warning in warnings:
                print(f"   • {warning}")
        
        print("\n" + "="*80)

    def _print_detailed_summary(self, results: Dict):
        """Выводит детальную сводку, включая диагностику ошибок."""
        print("\n" + "="*80)
        print("🎉 СВОДКА РЕЗУЛЬТАТОВ ОПТИМИЗАЦИИ")
        print("="*80)
        
        strategy_name = Path(results['strategy_config']).stem
        print(f"📋 Стратегия: {strategy_name}")
        print(f"⏱️  Время выполнения: {results['execution_time_minutes']:.1f} минут")
        print(f"🗓️  Дата: {results['timestamp']}")
        
        print("\n📊 СТАТИСТИКА ОКОН:")
        successful_windows = results['successful_windows']
        total_windows = results['total_windows']
        success_rate = (successful_windows / total_windows * 100) if total_windows > 0 else 0
        print(f"   ✅ Успешных окон: {successful_windows}/{total_windows} ({success_rate:.1f}%)")
        
        analysis = results.get('analysis', {})
        if analysis and analysis.get('status') != 'insufficient_data':
            overfitting_score = analysis.get('overfitting_score', 0)
            print(f"   🎯 Overfitting Score: {overfitting_score:.1f}/100")
            if overfitting_score < 40: verdict = "🟢 Низкий риск переоптимизации"
            elif overfitting_score < 70: verdict = "🟡 Умеренный риск переоптимизации"
            else: verdict = "🔴 Высокий риск переоптимизации"
            print(f"   📋 Оценка: {verdict}")

        # FIX: Выводим детальную диагностику, если не было успешных окон
        if successful_windows == 0:
            print("\n" + "-"*30 + " ДИАГНОСТИКА ПРОБЛЕМ " + "-"*30)
            rejections = results.get('total_rejection_summary')
            if not rejections:
                print("   Не найдено успешных окон. Причины отклонений не были зафиксированы.")
            else:
                total_failed_trials = sum(rejections.values())
                print(f"   Не найдено ни одного успешного окна. Анализ {total_failed_trials} неудачных попыток:")
                for reason, count in rejections.most_common():
                    percentage = (count / total_failed_trials) * 100 if total_failed_trials > 0 else 0
                    print(f"   - {percentage:.1f}% отклонено по причине: '{reason}'")
                print("\n   РЕКОМЕНДАЦИИ:")
                print("   - Проверьте логику стратегии: возможно, она совершает слишком мало сделок.")
                print("   - Расширьте диапазоны поиска параметров в файле конфигурации стратегии.")
                print("   - Пересмотрите критерии в 'risk_limits' и 'validation' в 'optimizer_config.json'.")

        best_params = results.get('best_parameters')
        if best_params:
            print(f"\n🏆 ЛУЧШИЕ РОБАСТНЫЕ ПАРАМЕТРЫ:")
            for param, value in best_params.items():
                print(f"   {param}: {value}")
        
        final_backtest = results.get('final_backtest')
        if final_backtest and final_backtest.get('success'):
            metrics = final_backtest.get('metrics')
            if metrics:
                print(f"\n💰 ФИНАЛЬНЫЙ БЭКТЕСТ:")
                print(f"   📈 Общая доходность: {metrics.total_return_pct:.2f}%")
                print(f"   📊 Sharpe Ratio: {metrics.sharpe_ratio:.3f}")
                print(f"   📊 Sortino Ratio: {metrics.sortino_ratio:.3f}")
                print(f"   📉 Max Drawdown: {metrics.max_drawdown_pct:.2f}%")
        
        warnings = results.get('overfitting_warnings', [])
        if warnings:
            print(f"\n⚠️ ПРЕДУПРЕЖДЕНИЯ:")
            for warning in warnings:
                print(f"   • {warning}")
        
        print("\n" + "="*80)


    def run_strategy_optimization(
        self,
        strategy_config_path: str,
        ticker: Optional[str] = None,
        period: Optional[str] = None,
        interval: Optional[str] = None,
    ):
        ticker_final = ticker or self.config.get("data_settings", {}).get("default_ticker", "AAPL")
        period_final = period or self.config.get("data_settings", {}).get("default_period", "1y")
        interval_final = interval or self.config.get("data_settings", {}).get("default_interval", "1d")

        try:
            data = self.load_data(ticker_final, period_final, interval_final)
            results = self.run_walk_forward_optimization(data, strategy_config_path)
            return results
        except Exception as e:
            print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
            raise


def main():
    parser = argparse.ArgumentParser(description="Продвинутый оптимизатор торговых стратегий")
    parser.add_argument("strategy_config", help="Путь к конфигу стратегии")
    parser.add_argument("--ticker", default=None, help="Тикер для оптимизации")
    parser.add_argument("--period", default=None, help="Период данных")
    parser.add_argument("--interval", default=None, help="Интервал данных")
    parser.add_argument("--config", default=None, help="Путь к конфигу оптимизатора")

    args = parser.parse_args()

    print("\n" + "="*80)
    print("🚀 ТОРГОВЫЙ ОПТИМИЗАТОР | Версия 2.0")
    print("="*80)

    try:
        strategy_path_str = args.strategy_config
        if "configsoptimizer" in strategy_path_str and '\\' not in strategy_path_str and '/' not in strategy_path_str:
            print("📝 ПОДСКАЗКА: Обнаружен некорректный путь к файлу конфигурации")
            corrected_path_str = strategy_path_str.replace('configsoptimizer', 'configs/optimizer/')
            print(f"🔧 Исправление: {corrected_path_str}")
            strategy_path_str = corrected_path_str

        strategy_path = Path(strategy_path_str).resolve()
        if not strategy_path.is_file():
            raise FileNotFoundError(f"Файл конфигурации стратегии не найден: {strategy_path}")

        print(f"📁 Конфиг стратегии: {strategy_path.name}")
        
        optimizer = AdvancedOptimizer(args.config)
        optimizer.run_strategy_optimization(str(strategy_path), args.ticker, args.period, args.interval)
        
    except Exception as e:
        print(f"\n❌ КРИТИЧЕСКАЯ ОШИБКА: {e}")
        exit(1)


if __name__ == "__main__":
    main()

