# Файл: optimizer/main_optimizer.py

import json
import logging
import time
import argparse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional, Any
import pandas as pd
import numpy as np
import yfinance as yf
from tqdm import tqdm
import optuna

# Импорты модулей оптимизатора
try:
    from .objective_function import OptimizerObjective
    from .validation_engine import ValidationEngine
    from .statistical_tests import StatisticalValidator
    # Прямой импорт классов из utils
    from .utils import OptimizerUtils, OptimizerReporter
except (ImportError, ValueError):
    # Fallback для прямого запуска
    import sys
    from pathlib import Path
    current_dir = Path(__file__).parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))
    
    try:
        from objective_function import OptimizerObjective
        from validation_engine import ValidationEngine
        from statistical_tests import StatisticalValidator
        # Прямой импорт классов из utils
        from utils import OptimizerUtils, OptimizerReporter
    except ImportError as e:
        print(f"⚠️ Проблема с импортами: {e}")
        print("Убедитесь, что все файлы находятся в папке optimizer/")
        
        # Последняя попытка - прямой импорт через importlib
        try:
            import importlib.util
            
            # Импорт utils
            utils_path = current_dir / "utils.py"
            spec = importlib.util.spec_from_file_location("utils", utils_path)
            utils_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(utils_module)
            
            OptimizerUtils = utils_module.OptimizerUtils
            OptimizerReporter = utils_module.OptimizerReporter
            
            print("✅ Успешно импортировали через importlib")
            
        except Exception as final_e:
            print(f"❌ Критическая ошибка импорта: {final_e}")
            raise


class AdvancedOptimizer:
    """
    Продвинутая система оптимизации торговых стратегий с защитой от overfitting.
    
    Основные принципы:
    1. Трехчастное разделение данных (train/validation/test)
    2. Walk-forward анализ с адаптивными параметрами
    3. Статистическая валидация результатов
    4. Детекция переоптимизации
    5. Робастность-тесты
    """
    
    def __init__(self, config_path: Optional[str] = None):
        """Инициализация оптимизатора с конфигурацией."""
        self.config_path = config_path if config_path else str(Path(__file__).parent / "optimizer_config.json")
        self.config = self._load_config()
        self._setup_logging()
        self._setup_directories()
        
        # Компоненты системы
        self.objective = OptimizerObjective(self.config)
        self.validator = ValidationEngine(self.config)
        self.statistical = StatisticalValidator(self.config)
        self.utils = OptimizerUtils(self.config)
        self.reporter = OptimizerReporter(self.config)
        
        # Результаты
        self.results = {}
        self.overfitting_warnings = []
        
    def _load_config(self) -> Dict:
        """Загружает конфигурацию оптимизатора."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config = json.load(f)
            return config
        except FileNotFoundError:
            raise FileNotFoundError(f"Конфиг не найден: {self.config_path}")
        except json.JSONDecodeError as e:
            raise ValueError(f"Ошибка в JSON конфиге: {e}")
    
    def _setup_logging(self):
        """Настройка логирования."""
        log_config = self.config['logging']
        level = getattr(logging, log_config['level'])
        
        handlers = []
        handlers.append(logging.StreamHandler())
        if log_config['save_to_file']:
            log_file = Path(__file__).parent / log_config['log_file']
            handlers.append(logging.FileHandler(log_file))
        
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=handlers
        )
        self.logger = logging.getLogger(__name__)
        
        # Отключаем лишние логи Optuna если не нужна детализация
        if not log_config['verbose_trials']:
            optuna.logging.set_verbosity(optuna.logging.WARNING)
    
    def _setup_directories(self):
        """Создание необходимых директорий."""
        charts_dir = Path(self.config['reporting']['charts_directory'])
        charts_dir.mkdir(parents=True, exist_ok=True)
    
    def load_data(self, ticker: Optional[str] = None, period: Optional[str] = None, interval: Optional[str] = None) -> pd.DataFrame:
        """Загрузка исторических данных с валидацией."""
        data_config = self.config['data_settings']
        
        ticker = ticker or data_config['default_ticker']
        period = period or data_config['default_period']
        interval = interval or data_config['default_interval']
        
        self.logger.info(f"⏳ Загружаем данные: {ticker}, {period}, {interval}")
        
        try:
            df = yf.download(tickers=ticker, period=period, interval=interval, auto_adjust=True)
            
            if df is None or df.empty:
                raise ValueError(f"Не удалось загрузить данные для {ticker}")
            
            # Валидация минимального количества данных
            min_points = data_config['min_data_points']
            if len(df) < min_points:
                raise ValueError(f"Недостаточно данных: {len(df)} < {min_points}")
            
            self.logger.info(f"✅ Данные загружены: {len(df)} свечей ({df.index[0].date()} → {df.index[-1].date()})")
            return df
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка загрузки данных: {e}")
            raise
    
    def create_data_splits(self, data: pd.DataFrame) -> List[Dict]:
        """
        Создает окна walk-forward с трехчастным разделением.
        
        Returns:
            List[Dict]: Список окон с train/validation/test периодами
        """
        wf_config = self.config['walk_forward']
        
        total_months = wf_config['train_months'] + wf_config['validation_months'] + wf_config['test_months']
        step_months = wf_config['step_months']
        
        start_date = data.index[0]
        end_date = data.index[-1]
        
        windows = []
        current_start = start_date
        
        while True:
            # Определяем границы окна
            train_end = current_start + pd.DateOffset(months=wf_config['train_months'])
            val_end = train_end + pd.DateOffset(months=wf_config['validation_months'])
            test_end = val_end + pd.DateOffset(months=wf_config['test_months'])
            
            # Проверяем, что у нас достаточно данных
            if test_end > end_date:
                break
            
            # Создаем окно
            window = {
                'window_id': len(windows) + 1,
                'train_start': current_start,
                'train_end': train_end,
                'val_start': train_end,
                'val_end': val_end,
                'test_start': val_end,
                'test_end': test_end,
                'train_data': data.loc[current_start:train_end],
                'val_data': data.loc[train_end:val_end],
                'test_data': data.loc[val_end:test_end]
            }
            
            windows.append(window)
            current_start += pd.DateOffset(months=step_months)
            
            # Ограничения на количество окон
            if len(windows) >= wf_config['max_windows']:
                break
        
        # Проверяем минимальное количество окон
        if len(windows) < wf_config['min_windows']:
            raise ValueError(f"Недостаточно данных для walk-forward: {len(windows)} < {wf_config['min_windows']}")
        
        self.logger.info(f"📊 Создано {len(windows)} окон walk-forward")
        return windows
    
    def optimize_single_window(self, window: Dict, strategy_config_path: str) -> Dict:
        """
        Оптимизация одного окна с валидацией.
        
        Args:
            window: Окно данных с train/validation/test
            strategy_config_path: Путь к конфигу стратегии
            
        Returns:
            Dict: Результаты оптимизации окна
        """
        window_id = window['window_id']
        opt_config = self.config['optimization']
        
        self.logger.info(f"🔍 Оптимизация окна {window_id}")
        
        # Создаем study для Optuna
        study = optuna.create_study(
            direction=opt_config['study_direction'],
            study_name=f"window_{window_id}_{int(time.time())}"
        )
        
        # Настраиваем objective function
        objective_func = lambda trial: self.objective.evaluate(
            trial, window['train_data'], strategy_config_path, mode='train'
        )
        
        # Запускаем оптимизацию с прогресс-баром
        with tqdm(total=opt_config['trials_per_window'], 
                 desc=f"Окно {window_id}", 
                 leave=False,
                 disable=not self.config['logging']['show_progress_bars']) as pbar:
            
            def callback(study, trial):
                pbar.update(1)
                if trial.value is not None:
                    pbar.set_postfix({
                        'Best': f"{study.best_value:.3f}",
                        'Current': f"{trial.value:.3f}"
                    })
            
            study.optimize(
                objective_func,
                n_trials=opt_config['trials_per_window'],
                timeout=opt_config['timeout_minutes'] * 60,
                callbacks=[callback],
                n_jobs=opt_config['n_jobs']
            )
        
        best_params = study.best_trial.params
        train_score = study.best_trial.value
        
        # Валидация на validation set
        val_result = self.objective.evaluate_fixed_params(
            best_params, window['val_data'], strategy_config_path, mode='validation'
        )
        val_score = val_result.get('score', 0.0)
        
        # Финальный тест на test set
        test_result = self.objective.evaluate_fixed_params(
            best_params, window['test_data'], strategy_config_path, mode='test'
        )
        test_score = test_result.get('score', 0.0)

        # Проверка на overfitting
        if train_score is None:
            overfitting_detected = True
        else:
            overfitting_detected = self.validator.detect_overfitting(
                train_score, val_score, test_score
            )
        
        # Статистическая валидация
        if test_result['trades']:
            statistical_valid = self.statistical.validate_trades(test_result['trades'])
        else:
            statistical_valid = False
        
        window_result = {
            'window_id': window_id,
            'train_period': f"{window['train_start'].date()} → {window['train_end'].date()}",
            'val_period': f"{window['val_start'].date()} → {window['val_end'].date()}",
            'test_period': f"{window['test_start'].date()} → {window['test_end'].date()}",
            'best_params': best_params,
            'train_score': train_score,
            'val_score': val_score,
            'test_score': test_score,
            'test_metrics': test_result['metrics'],
            'test_trades': len(test_result['trades']) if test_result['trades'] else 0,
            'overfitting_detected': overfitting_detected,
            'statistical_valid': statistical_valid,
            'success': test_score > 0 and not overfitting_detected and statistical_valid
        }
        
        return window_result
    
    def run_walk_forward_optimization(self, data: pd.DataFrame, strategy_config_path: str) -> Dict:
        """
        Главный метод: полный walk-forward анализ.
        
        Args:
            data: Исторические данные
            strategy_config_path: Путь к конфигу стратегии
            
        Returns:
            Dict: Полные результаты оптимизации
        """
        self.logger.info("🚀 НАЧИНАЕМ WALK-FORWARD ОПТИМИЗАЦИЮ")
        start_time = time.time()
        
        # Создаем окна данных
        windows = self.create_data_splits(data)
        
        # Оптимизируем каждое окно
        window_results = []
        for window in windows:
            try:
                result = self.optimize_single_window(window, strategy_config_path)
                window_results.append(result)
            except Exception as e:
                self.logger.error(f"❌ Ошибка в окне {window['window_id']}: {e}")
                # Добавляем результат с ошибкой
                error_result = {
                    'window_id': window['window_id'],
                    'success': False,
                    'error': str(e)
                }
                window_results.append(error_result)
        
        # Анализируем общие результаты
        analysis = self.validator.analyze_walk_forward_results(window_results)
        
        # Находим лучшие параметры
        best_params = self.utils.find_robust_parameters(window_results)
        
        # Финальный backtest на всех данных
        final_backtest = None
        if best_params:
            self.logger.info("🏆 Запускаем финальный backtest с лучшими параметрами")
            final_backtest = self.objective.evaluate_fixed_params(
                best_params, data, strategy_config_path, mode='final'
            )
        
        duration = time.time() - start_time
        
        # Собираем итоговые результаты
        results = {
            'strategy_config': strategy_config_path,
            'total_windows': len(windows),
            'successful_windows': len([w for w in window_results if w.get('success', False)]),
            'window_results': window_results,
            'analysis': analysis,
            'best_parameters': best_params,
            'final_backtest': final_backtest,
            'execution_time_minutes': duration / 60,
            'overfitting_warnings': analysis.get('warnings', []),
            'timestamp': datetime.now().isoformat()
        }
        
        self.results = results
        
        # Генерируем отчеты
        self.reporter.generate_full_report(results, data)
        
        self.logger.info(f"🎉 ОПТИМИЗАЦИЯ ЗАВЕРШЕНА за {duration/60:.1f} мин")
        return results
    
    def run_strategy_optimization(self, strategy_config_path: str, 
                                ticker: Optional[str] = None, period: Optional[str] = None, interval: Optional[str] = None):
        """
        Полный цикл оптимизации стратегии.
        
        Args:
            strategy_config_path: Путь к конфигу стратегии
            ticker: Тикер для загрузки данных
            period: Период данных
            interval: Интервал данных
        """
        try:
            # Проверяем, что аргументы не None, чтобы удовлетворить type-checker
            ticker_final = ticker or self.config['data_settings']['default_ticker']
            period_final = period or self.config['data_settings']['default_period']
            interval_final = interval or self.config['data_settings']['default_interval']

            # Загружаем данные
            data = self.load_data(ticker_final, period_final, interval_final)
            
            # Запускаем оптимизацию
            results = self.run_walk_forward_optimization(data, strategy_config_path)
            
            # Выводим краткую сводку
            self.reporter.print_summary(results)
            
            return results
            
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка оптимизации: {e}")
            raise


def main():
    """Точка входа для командной строки."""
    parser = argparse.ArgumentParser(description="Продвинутый оптимизатор торговых стратегий")
    parser.add_argument("strategy_config", help="Путь к конфигу стратегии")
    parser.add_argument("--ticker", default=None, help="Тикер для оптимизации")
    parser.add_argument("--period", default=None, help="Период данных")
    parser.add_argument("--interval", default=None, help="Интервал данных")
    parser.add_argument("--config", default=None, help="Путь к конфигу оптимизатора")
    
    args = parser.parse_args()
    
    # Создаем и запускаем оптимизатор
    optimizer = AdvancedOptimizer(args.config)
    optimizer.run_strategy_optimization(
        args.strategy_config,
        args.ticker,
        args.period, 
        args.interval
    )


if __name__ == "__main__":
    main()
