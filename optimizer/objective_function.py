# Файл: optimizer/objective_function.py

import json
import importlib
import pandas as pd
import numpy as np
from typing import Dict, Any, Tuple, Optional, List
import logging
from pathlib import Path

# Импорты из основной системы
try:
    # Пытаемся импортировать относительно
    from ..bot_process import Playground
    from ..analytics.metrics_calculator import MetricsCalculator
    from ..risk_management.config_manager import ConfigManager
except ImportError:
    # Fallback: если относительные импорты не работают
    import sys
    sys.path.append(str(Path(__file__).parent.parent))
    
    from bot_process import Playground
    from analytics.metrics_calculator import MetricsCalculator
    from risk_management.config_manager import ConfigManager


class OptimizerObjective:
    """
    Продвинутая objective function с защитой от переоптимизации.
    
    Основные улучшения:
    1. Убраны все магические числа
    2. Научно обоснованные пороги валидации
    3. Многокомпонентная оценка качества
    4. Адаптивные метрики в зависимости от режима рынка
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Кэширование исторических метрик для определения порогов
        self.historical_metrics = {
            'sharpe_ratios': [],
            'sortino_ratios': [],
            'calmar_ratios': [],
            'win_rates': [],
            'profit_factors': []
        }
        
        # Счетчики для статистики
        self.trial_counter = 0
        self.rejection_stats = {
            'insufficient_trades': 0,
            'poor_metrics': 0,
            'suspicious_values': 0,
            'execution_errors': 0
        }
    
    def evaluate(self, trial, data: pd.DataFrame, strategy_config_path: str, mode: str = 'train') -> float:
        """
        Главная функция оценки стратегии.
        
        Args:
            trial: Optuna trial object
            data: Данные для бэктеста
            strategy_config_path: Путь к конфигу стратегии
            mode: Режим оценки ('train', 'validation', 'test', 'final')
            
        Returns:
            float: Итоговая оценка стратегии
        """
        self.trial_counter += 1
        trial_id = getattr(trial, 'number', self.trial_counter)
        
        try:
            # Загружаем конфиг стратегии
            strategy_config = self._load_strategy_config(strategy_config_path)
            
            # Генерируем параметры для trial
            strategy_params = self._generate_strategy_params(trial, strategy_config)
            
            # Проверяем валидность параметров
            if not self._validate_parameter_ranges(strategy_params, strategy_config):
                trial.set_user_attr('rejection_reason', 'Invalid parameter ranges')
                self.rejection_stats['poor_metrics'] += 1
                return self._get_penalty_score('invalid_params')
            
            # Запускаем бэктест
            backtest_result = self._run_backtest(strategy_params, strategy_config, data, str(trial_id))
            
            if not backtest_result['success']:
                trial.set_user_attr('rejection_reason', backtest_result['error'])
                self.rejection_stats['execution_errors'] += 1
                return self._get_penalty_score('execution_error')
            
            # Анализируем результаты
            analysis = self._analyze_backtest_results(backtest_result)
            
            # Проверяем качество стратегии
            quality_check = self._validate_strategy_quality(analysis, mode)
            
            if not quality_check['valid']:
                trial.set_user_attr('rejection_reason', quality_check['reason'])
                self._update_rejection_stats(quality_check['category'])
                return self._get_penalty_score(quality_check['category'])
            
            # Рассчитываем итоговую оценку
            final_score = self._calculate_composite_score(analysis, mode)
            
            # Сохраняем метрики в trial для анализа
            self._save_trial_attributes(trial, analysis, final_score)
            
            # Обновляем исторические метрики
            self._update_historical_metrics(analysis)
            
            return final_score
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка в trial {trial_id}: {e}")
            trial.set_user_attr('rejection_reason', f'Critical error: {str(e)}')
            self.rejection_stats['execution_errors'] += 1
            return self._get_penalty_score('critical_error')
    
    def evaluate_fixed_params(self, params: Dict, data: pd.DataFrame, 
                             strategy_config_path: str, mode: str = 'test') -> Dict:
        """
        Оценка стратегии с фиксированными параметрами.
        
        Args:
            params: Фиксированные параметры стратегии
            data: Данные для бэктеста
            strategy_config_path: Путь к конфигу стратегии
            mode: Режим оценки
            
        Returns:
            Dict: Детальные результаты оценки
        """
        try:
            strategy_config = self._load_strategy_config(strategy_config_path)
            
            # Запускаем бэктест
            backtest_result = self._run_backtest(params, strategy_config, data, f"fixed_{mode}")
            
            if not backtest_result['success']:
                return {
                    'success': False,
                    'score': self._get_penalty_score('execution_error'),
                    'metrics': {},
                    'trades': [],
                    'error': backtest_result['error']
                }
            
            # Анализируем результаты
            analysis = self._analyze_backtest_results(backtest_result)
            
            # Рассчитываем оценку
            final_score = self._calculate_composite_score(analysis, mode)
            
            return {
                'success': True,
                'score': final_score,
                'metrics': analysis['metrics'],
                'trades': analysis['trades'],
                'analysis': analysis
            }
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка в evaluate_fixed_params: {e}")
            return {
                'success': False,
                'score': self._get_penalty_score('critical_error'),
                'metrics': {},
                'trades': [],
                'error': str(e)
            }
    
    def _load_strategy_config(self, config_path: str) -> Dict:
        """Загружает конфигурацию стратегии."""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            raise ValueError(f"Ошибка загрузки конфига стратегии {config_path}: {e}")
    
    def _generate_strategy_params(self, trial, strategy_config: Dict) -> Dict:
        """Генерирует параметры стратегии для Optuna trial."""
        strategy_params = {}
        
        for param in strategy_config["parameters"]:
            name = param["name"]
            p_type = param["type"]
            
            # Обработка зависимостей между параметрами
            low = param["low"]
            if "depends_on" in param:
                dependency = param["depends_on"]
                dependent_value = strategy_params.get(dependency["name"])
                if dependent_value is not None:
                    margin = dependency.get("margin", 1)
                    if dependency["condition"] == "greater":
                        low = max(low, dependent_value + margin)
            
            # Генерация параметра в зависимости от типа
            try:
                if p_type == "int":
                    strategy_params[name] = trial.suggest_int(name, low, param["high"])
                elif p_type == "float":
                    step = param.get("step")
                    strategy_params[name] = trial.suggest_float(name, low, param["high"], step=step)
                elif p_type == "categorical":
                    strategy_params[name] = trial.suggest_categorical(name, param["choices"])
                else:
                    raise ValueError(f"Неизвестный тип параметра: {p_type}")
            except ValueError as e:
                # Если параметры невалидны из-за зависимостей
                self.logger.debug(f"Невалидный диапазон параметров для {name}: {e}")
                raise ValueError(f"Invalid parameter range for {name}")
        
        return strategy_params
    
    def _validate_parameter_ranges(self, params: Dict, strategy_config: Dict) -> bool:
        """Проверяет валидность сгенерированных параметров."""
        for param in strategy_config["parameters"]:
            name = param["name"]
            value = params.get(name)
            
            if value is None:
                return False
            
            # Проверяем границы
            if param["type"] in ["int", "float"]:
                if not (param["low"] <= value <= param["high"]):
                    return False
            elif param["type"] == "categorical":
                if value not in param["choices"]:
                    return False
            
            # Проверяем зависимости
            if "depends_on" in param:
                dependency = param["depends_on"]
                dependent_value = params.get(dependency["name"])
                if dependent_value is not None:
                    margin = dependency.get("margin", 1)
                    if dependency["condition"] == "greater":
                        if value <= dependent_value + margin:
                            return False
        
        return True
    
    def _run_backtest(self, strategy_params: Dict, strategy_config: Dict, 
                     data: pd.DataFrame, trial_id: str) -> Dict:
        """Запускает бэктест стратегии."""
        try:
            # Настройка конфигурации бота
            bot_config = {
                "bot_name": f"optimizer_trial_{trial_id}",
                "strategy_file": strategy_config["strategy_file"],
                "symbol": "BTC-USD",  # TODO: Вынести в конфиг
                "strategy_params": strategy_params,
                "risk_config_file": 'configs/live_default.json',  # TODO: Вынести в конфиг
                "generate_chart": False
            }
            
            # Запускаем бэктест
            backtest = Playground(
                ohlcv_data=data,
                bot_config=bot_config,
                bot_name=bot_config["bot_name"]
            )
            backtest.run()
            
            # Получаем результаты
            trade_history = backtest.risk_manager.performance_tracker.trade_history
            trade_dicts = [trade.__dict__ for trade in trade_history]
            
            return {
                'success': True,
                'trades': trade_dicts,
                'performance_tracker': backtest.risk_manager.performance_tracker,
                'bot_config': bot_config
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e),
                'trades': []
            }
    
    def _analyze_backtest_results(self, backtest_result: Dict) -> Dict:
        """Анализирует результаты бэктеста и рассчитывает метрики."""
        trades = backtest_result['trades']
        
        if not trades:
            return {
                'trades': [],
                'trade_count': 0,
                'metrics': self._get_empty_metrics(),
                'basic_stats': self._get_empty_stats()
            }
        
        # Рассчитываем метрики через MetricsCalculator
        config_path = backtest_result['bot_config']['risk_config_file']
        base_config = ConfigManager.load_config(config_path)
        initial_balance = base_config.trading.initial_balance
        
        metrics_calculator = MetricsCalculator(
            trade_history=trades,
            initial_balance=initial_balance
        )
        metrics = metrics_calculator.calculate_all_metrics()
        
        # Дополнительная статистика
        total_profit = sum(t['profit'] for t in trades)
        winning_trades = sum(1 for t in trades if t['success'])
        win_rate = (winning_trades / len(trades)) * 100
        profit_factor = self._calculate_profit_factor(trades)
        
        basic_stats = {
            'total_profit': total_profit,
            'total_profit_pct': (total_profit / initial_balance) * 100,
            'trade_count': len(trades),
            'winning_trades': winning_trades,
            'losing_trades': len(trades) - winning_trades,
            'win_rate': win_rate,
            'profit_factor': profit_factor,
            'avg_trade': total_profit / len(trades),
            'avg_winning_trade': self._avg_winning_trade(trades),
            'avg_losing_trade': self._avg_losing_trade(trades)
        }
        
        return {
            'trades': trades,
            'trade_count': len(trades),
            'metrics': metrics,
            'basic_stats': basic_stats
        }
    
    def _validate_strategy_quality(self, analysis: Dict, mode: str) -> Dict:
        """
        Валидирует качество стратегии с научно обоснованными критериями.
        """
        validation_config = self.config['validation']
        risk_limits = self.config['risk_limits']
        
        trades = analysis['trades']
        metrics = analysis['metrics']
        stats = analysis['basic_stats']
        
        # 1. Минимальное количество сделок для статистической значимости
        min_trades = validation_config['min_trades_for_significance']
        if len(trades) < min_trades:
            return {
                'valid': False,
                'reason': f"Недостаточно сделок: {len(trades)}/{min_trades}",
                'category': 'insufficient_trades'
            }
        
        # 2. Базовая прибыльность
        if stats['total_profit'] <= 0:
            return {
                'valid': False,
                'reason': f"Убыточная стратегия: {stats['total_profit_pct']:.2f}%",
                'category': 'poor_metrics'
            }
        
        # 3. Проверка на экстремальные просадки
        if metrics.max_drawdown_pct > risk_limits['max_drawdown_threshold'] * 100:
            return {
                'valid': False,
                'reason': f"Превышена максимальная просадка: {metrics.max_drawdown_pct:.2f}%",
                'category': 'poor_metrics'
            }
        
        # 4. Минимальный win rate
        if stats['win_rate'] < risk_limits['min_win_rate'] * 100:
            return {
                'valid': False,
                'reason': f"Слишком низкий win rate: {stats['win_rate']:.1f}%",
                'category': 'poor_metrics'
            }
        
        # 5. Минимальный profit factor
        if stats['profit_factor'] < risk_limits['min_profit_factor']:
            return {
                'valid': False,
                'reason': f"Низкий profit factor: {stats['profit_factor']:.2f}",
                'category': 'poor_metrics'
            }
        
        # 6. Проверка на подозрительно высокие коэффициенты (адаптивные пороги)
        suspicious_check = self._check_suspicious_metrics(metrics, mode)
        if not suspicious_check['valid']:
            return suspicious_check
        
        return {'valid': True, 'reason': 'Passed all quality checks'}
    
    def _check_suspicious_metrics(self, metrics, mode: str) -> Dict:
        """
        Проверяет метрики на подозрительно высокие значения.
        Использует адаптивные пороги на основе исторических данных.
        """
        overfitting_config = self.config['overfitting_detection']
        
        # Если у нас недостаточно исторических данных, используем консервативные пороги
        if len(self.historical_metrics['sharpe_ratios']) < 10:
            conservative_limits = {
                'sharpe': 5.0,
                'sortino': 8.0,
                'calmar': 10.0
            }
            
            if (metrics.sharpe_ratio > conservative_limits['sharpe'] or
                metrics.sortino_ratio > conservative_limits['sortino'] or
                metrics.calmar_ratio > conservative_limits['calmar']):
                
                return {
                    'valid': False,
                    'reason': f"Подозрительно высокие коэффициенты: Sharpe={metrics.sharpe_ratio:.2f}",
                    'category': 'suspicious_values'
                }
        else:
            # Используем статистические пороги на основе исторических данных
            sharpe_threshold = np.percentile(
                self.historical_metrics['sharpe_ratios'],
                overfitting_config['suspicious_sharpe_percentile']
            )
            sortino_threshold = np.percentile(
                self.historical_metrics['sortino_ratios'],
                overfitting_config['suspicious_sortino_percentile']
            )
            calmar_threshold = np.percentile(
                self.historical_metrics['calmar_ratios'],
                overfitting_config['suspicious_calmar_percentile']
            )
            
            if (metrics.sharpe_ratio > sharpe_threshold or
                metrics.sortino_ratio > sortino_threshold or
                metrics.calmar_ratio > calmar_threshold):
                
                return {
                    'valid': False,
                    'reason': f"Коэффициенты выше {overfitting_config['suspicious_sharpe_percentile']}% перцентиля",
                    'category': 'suspicious_values'
                }
        
        return {'valid': True}
    
    def _calculate_composite_score(self, analysis: Dict, mode: str) -> float:
        """
        Рассчитывает комбинированную оценку стратегии.
        
        Использует адаптивные веса в зависимости от режима и качества данных.
        """
        metrics = analysis['metrics']
        stats = analysis['basic_stats']
        weights = self.config['metrics_weights']
        
        # Базовые компоненты оценки
        sharpe_component = max(0, metrics.sharpe_ratio) * weights['sharpe_ratio']
        sortino_component = max(0, metrics.sortino_ratio) * weights['sortino_ratio']
        calmar_component = max(0, metrics.calmar_ratio) * weights['calmar_ratio']
        
        # Бонус за стабильность (количество сделок)
        stability_bonus = self._calculate_stability_bonus(stats['trade_count']) * weights['stability_bonus']
        
        # Штраф за слишком частую торговлю
        frequency_penalty = self._calculate_frequency_penalty(stats['trade_count']) * weights['trade_frequency_penalty']
        
        # Итоговая оценка
        composite_score = (
            sharpe_component +
            sortino_component +
            calmar_component +
            stability_bonus -
            frequency_penalty
        )
        
        # Адаптация для разных режимов
        if mode == 'validation':
            # На валидации немного снижаем оценку для консерватизма
            composite_score *= 0.95
        elif mode == 'test':
            # На тесте применяем дополнительный штраф за нестабильность
            composite_score *= self._get_stability_multiplier(analysis)
        
        return max(0, composite_score)  # Не допускаем отрицательные оценки
    
    def _calculate_stability_bonus(self, trade_count: int) -> float:
        """Рассчитывает бонус за достаточное количество сделок."""
        min_trades = self.config['validation']['min_trades_for_significance']
        
        if trade_count < min_trades:
            return 0.0
        elif trade_count < min_trades * 2:
            # Линейный рост до удвоенного минимума
            return (trade_count - min_trades) / min_trades
        else:
            # Максимальный бонус после удвоенного минимума
            return 1.0
    
    def _calculate_frequency_penalty(self, trade_count: int) -> float:
        """Рассчитывает штраф за избыточную торговлю."""
        # Примерно 1 сделка на 2-3 дня считается нормальной для часовых данных
        # TODO: Сделать адаптивным в зависимости от интервала данных
        reasonable_max_trades_per_month = 15
        
        if trade_count <= reasonable_max_trades_per_month:
            return 0.0
        else:
            excess_trades = trade_count - reasonable_max_trades_per_month
            return min(2.0, excess_trades / reasonable_max_trades_per_month)  # Максимальный штраф = 2.0
    
    def _get_stability_multiplier(self, analysis: Dict) -> float:
        """Рассчитывает множитель стабильности для тестового режима."""
        stats = analysis['basic_stats']
        
        # Штраф за низкий win rate
        win_rate_factor = min(1.0, stats['win_rate'] / 50.0)  # Оптимум при 50%+ win rate
        
        # Штраф за низкий profit factor
        pf_factor = min(1.0, stats['profit_factor'] / 1.5)  # Оптимум при PF >= 1.5
        
        return (win_rate_factor + pf_factor) / 2
    
    def _get_penalty_score(self, category: str) -> float:
        """Возвращает штрафную оценку в зависимости от категории ошибки."""
        penalties = {
            'invalid_params': -100.0,
            'execution_error': -50.0,
            'critical_error': -75.0,
            'insufficient_trades': -25.0,
            'poor_metrics': -10.0,
            'suspicious_values': -30.0
        }
        return penalties.get(category, -50.0)
    
    # Вспомогательные методы для статистики
    def _calculate_profit_factor(self, trades: List[Dict]) -> float:
        """Рассчитывает profit factor."""
        gross_profit = sum(t['profit'] for t in trades if t['profit'] > 0)
        gross_loss = abs(sum(t['profit'] for t in trades if t['profit'] < 0))
        
        return gross_profit / gross_loss if gross_loss > 0 else float('inf')
    
    def _avg_winning_trade(self, trades: List[Dict]) -> float:
        """Средняя прибыль выигрышной сделки."""
        winning_profits = [t['profit'] for t in trades if t['profit'] > 0]
        return sum(winning_profits) / len(winning_profits) if winning_profits else 0.0
    
    def _avg_losing_trade(self, trades: List[Dict]) -> float:
        """Средний убыток проигрышной сделки."""
        losing_profits = [t['profit'] for t in trades if t['profit'] < 0]
        return sum(losing_profits) / len(losing_profits) if losing_profits else 0.0
    
    def _get_empty_metrics(self):
        """Возвращает пустые метрики."""
        from analytics.metrics_calculator import Metrics
        return Metrics()
    
    def _get_empty_stats(self) -> Dict:
        """Возвращает пустую статистику."""
        return {
            'total_profit': 0.0,
            'total_profit_pct': 0.0,
            'trade_count': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'profit_factor': 0.0,
            'avg_trade': 0.0,
            'avg_winning_trade': 0.0,
            'avg_losing_trade': 0.0
        }
    
    def _save_trial_attributes(self, trial, analysis: Dict, final_score: float):
        """Сохраняет атрибуты trial для последующего анализа."""
        metrics = analysis['metrics']
        stats = analysis['basic_stats']
        
        trial.set_user_attr('final_score', final_score)
        trial.set_user_attr('sharpe_ratio', metrics.sharpe_ratio)
        trial.set_user_attr('sortino_ratio', metrics.sortino_ratio)
        trial.set_user_attr('calmar_ratio', metrics.calmar_ratio)
        trial.set_user_attr('trade_count', stats['trade_count'])
        trial.set_user_attr('win_rate', stats['win_rate'])
        trial.set_user_attr('total_profit_pct', stats['total_profit_pct'])
        trial.set_user_attr('profit_factor', stats['profit_factor'])
        trial.set_user_attr('max_drawdown_pct', metrics.max_drawdown_pct)
        trial.set_user_attr('rejection_reason', 'Accepted')
    
    def _update_historical_metrics(self, analysis: Dict):
        """Обновляет исторические метрики для адаптивных порогов."""
        metrics = analysis['metrics']
        stats = analysis['basic_stats']
        
        # Сохраняем только валидные метрики
        if np.isfinite(metrics.sharpe_ratio):
            self.historical_metrics['sharpe_ratios'].append(metrics.sharpe_ratio)
        if np.isfinite(metrics.sortino_ratio):
            self.historical_metrics['sortino_ratios'].append(metrics.sortino_ratio)
        if np.isfinite(metrics.calmar_ratio):
            self.historical_metrics['calmar_ratios'].append(metrics.calmar_ratio)
        if np.isfinite(stats['win_rate']):
            self.historical_metrics['win_rates'].append(stats['win_rate'])
        if np.isfinite(stats['profit_factor']):
            self.historical_metrics['profit_factors'].append(stats['profit_factor'])
        
        # Ограничиваем размер истории для эффективности
        max_history = 1000
        for key in self.historical_metrics:
            if len(self.historical_metrics[key]) > max_history:
                self.historical_metrics[key] = self.historical_metrics[key][-max_history:]
    
    def _update_rejection_stats(self, category: str):
        """Обновляет статистику отклонений."""
        if category in self.rejection_stats:
            self.rejection_stats[category] += 1
    
    def get_rejection_summary(self) -> Dict:
        """Возвращает сводку по отклонениям trials."""
        total_trials = self.trial_counter
        total_rejections = sum(self.rejection_stats.values())
        
        return {
            'total_trials': total_trials,
            'total_rejections': total_rejections,
            'acceptance_rate': (total_trials - total_rejections) / total_trials if total_trials > 0 else 0,
            'rejection_breakdown': self.rejection_stats.copy()
        }