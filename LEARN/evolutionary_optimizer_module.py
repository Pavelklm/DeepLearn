# Файл: evolutionary_optimizer_module.py
# Полностью переписанный модуль для поиска стратегий через эволюцию
# ОБНОВЛЕНО: Переведено с pandas_ta на TA-Lib для улучшенной совместимости с Windows

import json
import logging
import random
import copy
import time
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Any, Optional
from pathlib import Path
from tqdm import tqdm
import pandas as pd
import yfinance as yf
import talib
import multiprocessing as mp
from functools import partial
from concurrent.futures import ProcessPoolExecutor, as_completed

# Исправляем пути для импортов
import sys
from pathlib import Path

# Добавляем корневую папку проекта в sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Импорты из основной системы
try:
    from analytics.metrics_calculator import MetricsCalculator
    from risk_management.config_manager import ConfigManager
    from bot_process import Playground
except ImportError as e:
    print(f"❌ Ошибка импорта: {e}")
    print("💡 Попробуйте запустить скрипт из корневой папки проекта:")
    print(f"   cd {project_root}")
    print(f"   python LEARN/evolutionary_optimizer_module.py")
    raise


def evaluate_individual_worker(individual: Dict, config: Dict, data_dict: Dict) -> Dict:
    """
    Worker функция для параллельной оценки особей.
    Выполняется в отдельном процессе.
    """
    try:
        # Восстанавливаем DataFrame из словаря
        data = pd.DataFrame(data_dict['data'], index=pd.to_datetime(data_dict['index']))
        
        # Создаем генератор сигналов
        signal_generator = SignalGenerator(config)
        signals = signal_generator.generate_signals(individual, data)
        
        if not signals or len(signals) < config['validation']['min_trades_threshold']:
            return {
                'success': False,
                'score': config['scoring']['penalties']['insufficient_signals'],
                'metrics': {},
                'trades': [],
                'signals_count': len(signals) if signals else 0
            }
        
        # Запускаем легковесный бэктест
        runner = LightweightBacktester(config)
        backtest_result = runner.run_backtest(signals, data)
        
        if not backtest_result['success']:
            return {
                'success': False,
                'score': config['scoring']['penalties']['backtest_failed'],
                'metrics': {},
                'trades': [],
                'error': backtest_result.get('error', 'Unknown error')
            }
        
        # Анализируем результаты (упрощенно)
        trades = backtest_result['trades']
        metrics = backtest_result.get('metrics', {})
        
        if not trades:
            return {
                'success': False,
                'score': config['scoring']['penalties']['insufficient_trades'],
                'metrics': {},
                'trades': []
            }
        
        # Быстрая валидация
        total_profit = metrics.get('total_profit', 0)
        win_rate = metrics.get('win_rate', 0)
        
        if total_profit <= 0:
            return {
                'success': False,
                'score': config['scoring']['penalties']['unprofitable'],
                'metrics': metrics,
                'trades': trades
            }
        
        if win_rate < config['validation']['min_win_rate']:
            return {
                'success': False,
                'score': config['scoring']['penalties']['low_win_rate'],
                'metrics': metrics,
                'trades': trades
            }
        
        # Быстрый расчет оценки
        weights = config['scoring']['weights']
        return_pct = metrics.get('return_pct', 0)
        trade_count = len(trades)
        
        # Упрощенная формула оценки
        profit_component = max(0, return_pct / 100) * weights['profit_factor']
        win_rate_component = win_rate * weights['win_rate']
        
        # Бонус за оптимальное количество сделок
        optimal_range = config['scoring']['optimal_trade_range']
        if optimal_range[0] <= trade_count <= optimal_range[1]:
            trade_bonus = weights['trade_frequency']
        else:
            trade_bonus = weights['trade_frequency'] * 0.5
        
        final_score = profit_component + win_rate_component + trade_bonus
        
        return {
            'success': True,
            'score': max(0, final_score),
            'metrics': metrics,
            'trades': trades,
            'trade_count': trade_count
        }
        
    except Exception as e:
        return {
            'success': False,
            'score': config['scoring']['penalties']['critical_error'],
            'metrics': {},
            'trades': [],
            'error': str(e)
        }


class SimpleMetrics:
    """
    Простые метрики для легковесного бэктеста.
    """
    def __init__(self, total_profit: float, return_pct: float, total_trades: int, win_rate: float):
        self.total_profit = total_profit
        self.return_pct = return_pct
        self.total_trades = total_trades
        self.win_rate = win_rate
        # Упрощенные метрики
        self.sharpe_ratio = max(0, return_pct / 10)  # Примитивная оценка
        self.max_drawdown_pct = abs(min(0, return_pct / 2))  # Оценка просадки
        

class StrategyDiscoveryObjective:
    """
    Оценщик сгенерированных стратегий-кандидатов.
    Заменяет OptimizerObjective для задач генерации стратегий.
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.StrategyDiscoveryObjective")
        
        # Счетчики для статистики
        self.evaluation_count = 0
        self.successful_evaluations = 0
        
    def evaluate_strategy_candidate(self, candidate: Dict, data: pd.DataFrame) -> Dict:
        """
        Оценивает кандидата стратегии.
        
        Args:
            candidate: {"indicators": {...}, "trading_rules": {...}}
            data: Исторические данные для бэктеста
            
        Returns:
            {"score": float, "metrics": {...}, "trades": [...], "success": bool}
        """
        self.evaluation_count += 1
        start_time = time.time()
        # max_evaluation_time = 30  # Убираем таймаут пока
        
        try:
            # Генерируем торговые сигналы
            if self.evaluation_count % 100 == 1:  # Логируем каждую 100-ю оценку
                self.logger.info(f"    🔍 Генерируем сигналы для оценки #{self.evaluation_count}")
            
            signal_start = time.time()
            signal_generator = SignalGenerator(self.config)
            signals = signal_generator.generate_signals(candidate, data)
            signal_time = time.time() - signal_start
            
            # Убираем проверки таймаута
            
            if not signals or len(signals) < self.config['validation']['min_trades_threshold']:
                if self.evaluation_count % 50 == 1:  # Логируем причину провала
                    self.logger.warning(f"    ⚠️ Недостаточно сигналов: {len(signals) if signals else 0}/"
                                       f"{self.config['validation']['min_trades_threshold']}")
                return {
                    'success': False,
                    'score': self._get_penalty_score('insufficient_signals'),
                    'metrics': {},
                    'trades': [],
                    'signals_count': len(signals) if signals else 0
                }
            
            if self.evaluation_count % 100 == 1:
                self.logger.info(f"    💹 Запускаем бэктест с {len(signals)} сигналами (сигналы: {signal_time:.2f}с)")

            # Запускаем бэктест
            backtest_start = time.time()
            runner = LightweightBacktester(self.config)
            backtest_result = runner.run_backtest(signals, data)
            backtest_time = time.time() - backtest_start
            
            # Убираем проверку таймаута
            
            if not backtest_result['success']:
                if self.evaluation_count % 50 == 1:
                    self.logger.warning(f"    ⚠️ Бэктест провалился: {backtest_result.get('error', 'Unknown error')}")
                return {
                    'success': False,
                    'score': self._get_penalty_score('backtest_failed'),
                    'metrics': {},
                    'trades': [],
                    'error': backtest_result.get('error', 'Unknown error')
                }
            
            # Анализируем результаты
            analysis_start = time.time()
            analysis = self._analyze_results(backtest_result)
            analysis_time = time.time() - analysis_start
            
            # Валидируем качество
            validation_start = time.time()
            validation = self._validate_quality(analysis)
            validation_time = time.time() - validation_start
            if not validation['valid']:
                if self.evaluation_count % 50 == 1:
                    self.logger.warning(f"    ⚠️ Валидация не прошла: {validation['reason']}")
                return {
                    'success': False,
                    'score': self._get_penalty_score(validation['category']),
                    'metrics': analysis['metrics'],
                    'trades': analysis['trades'],
                    'rejection_reason': validation['reason']
                }
            
            # Рассчитываем финальную оценку
            scoring_start = time.time()
            final_score = self._calculate_score(analysis)
            scoring_time = time.time() - scoring_start
            
            total_time = time.time() - start_time
            
            # Логируем время каждой 50-й оценки
            if self.evaluation_count % 50 == 0:
                self.logger.info(
                    f"    ⏱️ Оценка #{self.evaluation_count}: {total_time:.2f}с "
                    f"(сигналы: {signal_time:.2f}с, бэктест: {backtest_time:.2f}с, "
                    f"анализ: {analysis_time:.2f}с, валидация: {validation_time:.2f}с, "
                    f"оценка: {scoring_time:.2f}с)"
                )
            
            self.successful_evaluations += 1
            
            return {
                'success': True,
                'score': final_score,
                'metrics': analysis['metrics'],
                'trades': analysis['trades'],
                'trade_count': len(analysis['trades'])
            }
            
        except Exception as e:
            total_time = time.time() - start_time
            self.logger.warning(f"    ⚠️ Ошибка оценки #{self.evaluation_count} за {total_time:.2f}с: {e}")
            return {
                'success': False,
                'score': self._get_penalty_score('critical_error'),
                'metrics': {},
                'trades': [],
                'error': str(e)
            }
    
    def _analyze_results(self, backtest_result: Dict) -> Dict:
        """Анализирует результаты легковесного бэктеста."""
        trades = backtest_result['trades']
        metrics = backtest_result.get('metrics', {})
        
        if not trades:
            return {
                'trades': [],
                'trade_count': 0,
                'metrics': self._get_empty_metrics(),
                'basic_stats': self._get_empty_stats()
            }
        
        # Используем метрики из легковесного бэктеста
        total_profit = metrics.get('total_profit', 0)
        winning_trades = metrics.get('winning_trades', 0)
        win_rate = metrics.get('win_rate', 0) * 100  # Преобразуем в проценты
        
        # Создаем упрощенные метрики
        simple_metrics = SimpleMetrics(
            total_profit=total_profit,
            return_pct=metrics.get('return_pct', 0),
            total_trades=len(trades),
            win_rate=win_rate
        )
        
        basic_stats = {
            'total_profit': total_profit,
            'total_profit_pct': metrics.get('return_pct', 0),
            'trade_count': len(trades),
            'winning_trades': winning_trades,
            'losing_trades': len(trades) - winning_trades,
            'win_rate': win_rate,
            'avg_trade': total_profit / len(trades) if trades else 0
        }
        
        return {
            'trades': trades,
            'trade_count': len(trades),
            'metrics': simple_metrics,
            'basic_stats': basic_stats
        }
    
    def _validate_quality(self, analysis: Dict) -> Dict:
        """Валидирует качество стратегии."""
        trades = analysis['trades']
        metrics = analysis['metrics']
        stats = analysis['basic_stats']
        
        validation_config = self.config['validation']
        
        # Проверка количества сделок
        min_trades = validation_config['min_trades_threshold']
        max_trades = validation_config['max_trades_threshold']
        
        if len(trades) < min_trades:
            return {
                'valid': False,
                'reason': f"Слишком мало сделок: {len(trades)}/{min_trades}",
                'category': 'insufficient_trades'
            }
        
        if len(trades) > max_trades:
            return {
                'valid': False,
                'reason': f"Слишком много сделок: {len(trades)}/{max_trades}",
                'category': 'excessive_trades'
            }
        
        # Проверка базовой прибыльности
        if stats['total_profit'] <= 0:
            return {
                'valid': False,
                'reason': f"Убыточная стратегия: {stats['total_profit_pct']:.2f}%",
                'category': 'unprofitable'
            }
        
        # Проверка максимальной просадки
        max_dd_threshold = validation_config['max_drawdown_threshold']
        if hasattr(metrics, 'max_drawdown_pct') and metrics.max_drawdown_pct > max_dd_threshold * 100:
            return {
                'valid': False,
                'reason': f"Превышена максимальная просадка: {metrics.max_drawdown_pct:.2f}%",
                'category': 'high_drawdown'
            }
        
        # Проверка win rate
        min_win_rate = validation_config['min_win_rate']
        if stats['win_rate'] < min_win_rate * 100:
            return {
                'valid': False,
                'reason': f"Низкий win rate: {stats['win_rate']:.1f}%",
                'category': 'low_win_rate'
            }
        
        return {'valid': True}
    
    def _calculate_score(self, analysis: Dict) -> float:
        """Рассчитывает итоговую оценку стратегии."""
        metrics = analysis['metrics']
        stats = analysis['basic_stats']
        weights = self.config['scoring']['weights']
        
        # Базовые компоненты
        sharpe_component = max(0, getattr(metrics, 'sharpe_ratio', 0)) * weights['sharpe_ratio']
        profit_component = max(0, stats['total_profit_pct'] / 100) * weights['profit_factor']
        win_rate_component = (stats['win_rate'] / 100) * weights['win_rate']
        
        # Бонус за оптимальное количество сделок
        trade_count_bonus = self._calculate_trade_frequency_score(stats['trade_count']) * weights['trade_frequency']
        
        # Штраф за высокую просадку
        dd_penalty = 0
        if hasattr(metrics, 'max_drawdown_pct'):
            dd_penalty = max(0, metrics.max_drawdown_pct / 100) * weights['drawdown_penalty']
        
        final_score = (
            sharpe_component +
            profit_component +
            win_rate_component +
            trade_count_bonus -
            dd_penalty
        )
        
        return max(0, final_score)
    
    def _calculate_trade_frequency_score(self, trade_count: int) -> float:
        """Рассчитывает оценку частоты торговли."""
        optimal_range = self.config['scoring']['optimal_trade_range']
        min_optimal, max_optimal = optimal_range
        
        if min_optimal <= trade_count <= max_optimal:
            return 1.0  # Максимальная оценка
        elif trade_count < min_optimal:
            # Штраф за слишком редкую торговлю
            return trade_count / min_optimal
        else:
            # Штраф за слишком частую торговлю
            excess = trade_count - max_optimal
            penalty = min(0.8, excess / max_optimal)  # Максимальный штраф 80%
            return max(0.2, 1.0 - penalty)
    
    def _get_penalty_score(self, category: str) -> float:
        """Возвращает штрафную оценку."""
        penalties = self.config['scoring']['penalties']
        return penalties.get(category, penalties['default'])
    
    def _get_empty_metrics(self):
        """Возвращает пустые метрики."""
        class EmptyMetrics:
            def __init__(self):
                self.sharpe_ratio = 0.0
                self.sortino_ratio = 0.0
                self.max_drawdown_pct = 0.0
        return EmptyMetrics()
    
    def _get_empty_stats(self) -> Dict:
        """Возвращает пустую статистику."""
        return {
            'total_profit': 0.0,
            'total_profit_pct': 0.0,
            'trade_count': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'avg_trade': 0.0
        }


class SignalGenerator:
    """
    Генератор торговых сигналов из спецификации стратегии.
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.SignalGenerator")
        self.current_position = None  # None, "LONG", "SHORT"
        
        # Статистика для логирования
        self.generation_count = 0
        self.successful_generations = 0
        
    def generate_signals(self, candidate: Dict, data: pd.DataFrame) -> List[Dict]:
        """
        Генерирует торговые сигналы из кандидата стратегии.
        
        Returns:
            List[{"timestamp": datetime, "signal": str, "price": float}]
            где signal in ["LONG_ENTRY", "LONG_EXIT", "SHORT_ENTRY", "SHORT_EXIT", "HOLD"]
        """
        self.generation_count += 1
        
        try:
            # Сбрасываем позицию для новой стратегии
            self.current_position = None
            
            # Подготавливаем данные с индикаторами
            enriched_data = self._add_indicators(data.copy(), candidate['indicators'])
            
            # Проверяем, что индикаторы добавились
            new_columns = [col for col in enriched_data.columns if col not in data.columns]
            if len(candidate['indicators']) > 0 and len(new_columns) == 0:
                self.logger.warning(f"Индикаторы не добавились! Запрошено: {list(candidate['indicators'].keys())}")
                return []
            
            # Логируем результат добавления индикаторов
            if self.generation_count % 100 == 1:  # Каждые 100 поколений
                self.logger.info(f"Добавлено индикаторов: {new_columns}")
            
            # Парсим торговые правила
            rules = self._parse_trading_rules(candidate['trading_rules'])
            
            # Генерируем сигналы
            signals = []
            loop_iterations = 0
            holds_count = 0
            
            for i in range(len(enriched_data)):
                if i < self.config['signal_generation']['min_history_bars']:
                    continue  # Пропускаем первые бары для корректного расчета индикаторов
                
                loop_iterations += 1
                row = enriched_data.iloc[i]
                signal = self._evaluate_rules(rules, row, enriched_data, i, self.current_position)
                
                if signal == "HOLD":
                    holds_count += 1
                else:
                    signals.append({
                        'timestamp': row.name,
                        'signal': signal,
                        'price': row['Close']
                    })
                    
                    # Обновляем текущую позицию
                    if signal in ["LONG_ENTRY"]:
                        self.current_position = "LONG"
                    elif signal in ["SHORT_ENTRY"]:
                        self.current_position = "SHORT"
                    elif signal in ["LONG_EXIT", "SHORT_EXIT"]:
                        self.current_position = None
            
            # Логируем результаты генерации сигналов
            if len(signals) > 0:
                self.successful_generations += 1
            
            if len(signals) == 0 and loop_iterations > 0:
                if self.generation_count % 50 == 0:  # Каждые 50 поколений
                    self.logger.warning(
                        f"Стратегия #{self.generation_count}: Ни одного сигнала! Итераций: {loop_iterations}, "
                        f"HOLD: {holds_count}, Условия: {len(rules['long_entry']) + len(rules['short_entry'])}"
                    )
            elif self.generation_count % 200 == 0:  # Каждые 200 поколений - успешная статистика
                success_rate = (self.successful_generations / self.generation_count) * 100
                self.logger.info(
                    f"Статистика генерации сигналов: {self.successful_generations}/{self.generation_count} "
                    f"({success_rate:.1f}% успешных)"
                )
            
            return signals
            
        except Exception as e:
            self.logger.error(f"Ошибка генерации сигналов для стратегии #{self.generation_count}: {e}")
            return []
    
    def _add_indicators(self, data: pd.DataFrame, indicators: Dict) -> pd.DataFrame:
        """Добавляет индикаторы к данным."""
        enriched_data = data.copy()
        
        # Очищаем данные от NaN и приводим к правильному формату
        clean_data = data.dropna().copy()
        if len(clean_data) < 50:  # Минимум данных для индикаторов
            self.logger.warning("Недостаточно данных после очистки NaN")
            return enriched_data
        
        # Исправляем проблему с мультииндексными колонками от yfinance
        if isinstance(clean_data.columns, pd.MultiIndex):
            clean_data.columns = clean_data.columns.droplevel(1)
            enriched_data.columns = enriched_data.columns.droplevel(1) if isinstance(enriched_data.columns, pd.MultiIndex) else enriched_data.columns
        
        # Подготавливаем основные массивы (проверяем наличие колонок)
        try:
            close = clean_data['Close'].astype(float).values
            high = clean_data['High'].astype(float).values
            low = clean_data['Low'].astype(float).values
            volume = clean_data['Volume'].astype(float).values if 'Volume' in clean_data.columns else None
        except KeyError as e:
            self.logger.error(f"Отсутствует колонка: {e}. Доступные колонки: {list(clean_data.columns)}")
            return enriched_data
        except Exception as e:
            self.logger.error(f"Ошибка подготовки данных: {e}")
            return enriched_data
        
        # Проверяем размерности массивов
        if len(close) != len(high) or len(close) != len(low):
            self.logger.error("Неодинаковая длина массивов OHLC")
            return enriched_data
        
        # Проверяем форму массивов - должны быть одномерными
        if len(close.shape) > 1:
            self.logger.debug(f"Преобразуем многомерные массивы в одномерные")
        
        # Убеждаемся, что данные корректны для TA-Lib
        # Принудительно делаем одномерными и контигуоусными
        close = np.ascontiguousarray(close.flatten(), dtype=np.float64)
        high = np.ascontiguousarray(high.flatten(), dtype=np.float64)
        low = np.ascontiguousarray(low.flatten(), dtype=np.float64)
        if volume is not None:
            volume = np.ascontiguousarray(volume.flatten(), dtype=np.float64)
        
        # Проверяем, что TA-Lib работает корректно
        try:
            test_sma = talib.SMA(close[:100], timeperiod=10)  # Короткий тест
        except Exception as e:
            self.logger.error(f"TA-Lib не работает: {e}")
            return enriched_data
        
        for indicator_name, params in indicators.items():
            try:
                # Проверка минимального количества данных
                min_periods = params.get('timeperiod', 30) if 'timeperiod' in params else 30
                if len(close) < min_periods + 10:  # +10 для запаса
                    self.logger.warning(f"Недостаточно данных для {indicator_name}: {len(close)} < {min_periods + 10}")
                    continue
                    
                if hasattr(talib, indicator_name.upper()):
                    indicator_func = getattr(talib, indicator_name.upper())
                    
                    # Вызываем индикатор и добавляем результат в DataFrame
                    if indicator_name.upper() == 'RSI':
                        result = indicator_func(close, timeperiod=params.get('timeperiod', 14))
                        # Используем базовое имя вместо имени с параметрами
                        enriched_data['RSI'] = pd.Series(result, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'MACD':
                        macd, macdsignal, macdhist = indicator_func(
                            close, 
                            fastperiod=params.get('fastperiod', 12),
                            slowperiod=params.get('slowperiod', 26),
                            signalperiod=params.get('signalperiod', 9)
                        )
                        enriched_data['MACD'] = pd.Series(macd, index=clean_data.index)
                        enriched_data['MACD_signal'] = pd.Series(macdsignal, index=clean_data.index)
                        enriched_data['MACD_hist'] = pd.Series(macdhist, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'SMA':
                        result = indicator_func(close, timeperiod=params.get('timeperiod', 20))
                        enriched_data['SMA'] = pd.Series(result, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'EMA':
                        result = indicator_func(close, timeperiod=params.get('timeperiod', 20))
                        enriched_data['EMA'] = pd.Series(result, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'BBANDS':
                        upper, middle, lower = indicator_func(
                            close,
                            timeperiod=params.get('timeperiod', 20),
                            nbdevup=params.get('nbdevup', 2),
                            nbdevdn=params.get('nbdevdn', 2)
                        )
                        enriched_data['BB_upper'] = pd.Series(upper, index=clean_data.index)
                        enriched_data['BB_middle'] = pd.Series(middle, index=clean_data.index)
                        enriched_data['BB_lower'] = pd.Series(lower, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'STOCH':
                        slowk, slowd = indicator_func(
                            high, low, close,
                            fastk_period=params.get('fastk_period', 14),
                            slowk_period=params.get('slowk_period', 3),
                            slowd_period=params.get('slowd_period', 3)
                        )
                        enriched_data['STOCH_k'] = pd.Series(slowk, index=clean_data.index)
                        enriched_data['STOCH_d'] = pd.Series(slowd, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'ADX':
                        result = indicator_func(high, low, close, timeperiod=params.get('timeperiod', 14))
                        enriched_data['ADX'] = pd.Series(result, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'CCI':
                        result = indicator_func(high, low, close, timeperiod=params.get('timeperiod', 14))
                        enriched_data['CCI'] = pd.Series(result, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'MFI':
                        if volume is not None:
                            result = indicator_func(high, low, close, volume, timeperiod=params.get('timeperiod', 14))
                            enriched_data['MFI'] = pd.Series(result, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'WILLR':
                        result = indicator_func(high, low, close, timeperiod=params.get('timeperiod', 14))
                        enriched_data['WILLR'] = pd.Series(result, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'ATR':
                        result = indicator_func(high, low, close, timeperiod=params.get('timeperiod', 14))
                        enriched_data['ATR'] = pd.Series(result, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'OBV':
                        if volume is not None:
                            result = indicator_func(close, volume)
                            enriched_data['OBV'] = pd.Series(result, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'TEMA':
                        result = indicator_func(close, timeperiod=params.get('timeperiod', 30))
                        enriched_data['TEMA'] = pd.Series(result, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'DEMA':
                        result = indicator_func(close, timeperiod=params.get('timeperiod', 30))
                        enriched_data['DEMA'] = pd.Series(result, index=clean_data.index)
                    
                    elif indicator_name.upper() == 'KAMA':
                        result = indicator_func(close, timeperiod=params.get('timeperiod', 30))
                        enriched_data['KAMA'] = pd.Series(result, index=clean_data.index)
                    
                    else:
                        self.logger.warning(f"Индикатор {indicator_name} не обработан")
                        
                else:
                    self.logger.warning(f"Индикатор {indicator_name} не найден в TA-Lib")
            except Exception as e:
                self.logger.warning(f"Ошибка добавления индикатора {indicator_name}: {e}")
        
        # Возвращаем обогащенные данные с тем же индексом, что и исходные
        return enriched_data.reindex(data.index)
    
    def _parse_trading_rules(self, rules: Dict) -> Dict:
        """Парсит правила торговли."""
        parsed_rules = {
            'long_entry': rules.get('long_entry_conditions', []),
            'long_exit': rules.get('long_exit_conditions', []),
            'short_entry': rules.get('short_entry_conditions', []),
            'short_exit': rules.get('short_exit_conditions', []),
            'logic_operator': rules.get('logic_operator', 'AND')
        }
        return parsed_rules
    
    def _evaluate_rules(self, rules: Dict, row: pd.Series, data: pd.DataFrame, 
                       index: int, current_position: Optional[str]) -> str:
        """Оценивает правила и возвращает сигнал."""
        
        # Проверяем условия выхода (приоритет)
        if current_position == "LONG":
            if self._evaluate_conditions(rules['long_exit'], row, data, index, rules['logic_operator']):
                return "LONG_EXIT"
        elif current_position == "SHORT":
            if self._evaluate_conditions(rules['short_exit'], row, data, index, rules['logic_operator']):
                return "SHORT_EXIT"
        
        # Проверяем условия входа (только если нет позиции)
        if current_position is None:
            if self._evaluate_conditions(rules['long_entry'], row, data, index, rules['logic_operator']):
                return "LONG_ENTRY"
            elif self._evaluate_conditions(rules['short_entry'], row, data, index, rules['logic_operator']):
                return "SHORT_ENTRY"
        
        return "HOLD"
    
    def _evaluate_conditions(self, conditions: List[Dict], row: pd.Series, 
                           data: pd.DataFrame, index: int, logic_operator: str) -> bool:
        """Оценивает список условий."""
        if not conditions:
            return False
        
        # Логируем проверку условий через интервалы (убираем для упрощения)
        pass  # Убираем лишнее логирование для чистоты
        
        results = []
        for condition in conditions:
            result = self._evaluate_single_condition(condition, row, data, index)
            results.append(result)
        
        if logic_operator == "AND":
            return all(results)
        elif logic_operator == "OR":
            return any(results)
        else:
            return all(results)  # По умолчанию AND
    
    def _evaluate_single_condition(self, condition: Dict, row: pd.Series, 
                                 data: pd.DataFrame, index: int) -> bool:
        """Оценивает одно условие."""
        try:
            condition_type = condition['type']
            
            if condition_type == 'threshold':
                return self._evaluate_threshold(condition, row)
            elif condition_type == 'crossover':
                return self._evaluate_crossover(condition, data, index)
            elif condition_type == 'divergence':
                return self._evaluate_divergence(condition, data, index)
            else:
                return False
                
        except Exception as e:
            self.logger.warning(f"Ошибка оценки условия {condition}: {e}")
            return False
    
    def _evaluate_threshold(self, condition: Dict, row: pd.Series) -> bool:
        """Оценивает пороговые условия."""
        indicator = condition['indicator']
        operator = condition['operator']
        threshold = condition['threshold']
        
        if indicator not in row:
            return False
        
        value = row[indicator]
        
        # Проверяем, что значение является скаляром
        if hasattr(value, '__len__') and not isinstance(value, str):
            # Если это Series или массив, берем последнее значение
            if hasattr(value, 'iloc'):
                value = value.iloc[-1] if len(value) > 0 else np.nan
            else:
                value = value[-1] if len(value) > 0 else np.nan
        
        # Проверяем на NaN
        if pd.isna(value):
            return False
        
        # Преобразуем в float для безопасности
        try:
            value = float(value)
            threshold = float(threshold)
        except (ValueError, TypeError):
            return False
        
        if operator == '>':
            return value > threshold
        elif operator == '<':
            return value < threshold
        elif operator == '>=':
            return value >= threshold
        elif operator == '<=':
            return value <= threshold
        elif operator == '==':
            return abs(value - threshold) < 1e-6
        else:
            return False
    
    def _evaluate_crossover(self, condition: Dict, data: pd.DataFrame, index: int) -> bool:
        """Оценивает условия пересечения."""
        if index < 1:
            return False
        
        indicator1 = condition['indicator1']
        indicator2 = condition['indicator2']
        direction = condition.get('direction', 'above')  # 'above' или 'below'
        
        if indicator1 not in data.columns or indicator2 not in data.columns:
            return False
        
        # Получаем значения и преобразуем в скаляры
        def safe_scalar(val):
            if hasattr(val, '__len__') and not isinstance(val, str):
                if hasattr(val, 'iloc'):
                    return val.iloc[-1] if len(val) > 0 else np.nan
                else:
                    return val[-1] if len(val) > 0 else np.nan
            return val
        
        try:
            current_val1 = safe_scalar(data.iloc[index][indicator1])
            current_val2 = safe_scalar(data.iloc[index][indicator2])
            prev_val1 = safe_scalar(data.iloc[index-1][indicator1])
            prev_val2 = safe_scalar(data.iloc[index-1][indicator2])
            
            # Преобразуем в float
            current_val1 = float(current_val1)
            current_val2 = float(current_val2)
            prev_val1 = float(prev_val1)
            prev_val2 = float(prev_val2)
            
        except (ValueError, TypeError, IndexError):
            return False
        
        if any(pd.isna([current_val1, current_val2, prev_val1, prev_val2])):
            return False
        
        if direction == 'above':
            return prev_val1 <= prev_val2 and current_val1 > current_val2
        elif direction == 'below':
            return prev_val1 >= prev_val2 and current_val1 < current_val2
        else:
            return False
    
    def _evaluate_divergence(self, condition: Dict, data: pd.DataFrame, index: int) -> bool:
        """Оценивает дивергенции (упрощенная версия)."""
        lookback = condition.get('lookback', 10)
        if index < lookback:
            return False
        
        # Упрощенная проверка дивергенции
        # TODO: Реализовать полноценную логику дивергенций
        return False


class LightweightBacktester:
    """
    Легковесный бэктестер без тяжелой инициализации Playground.
    Выполняет только базовую симуляцию торговли.
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.initial_balance = config.get('performance', {}).get('initial_balance', 10000)
        self.commission = config.get('performance', {}).get('commission', 0.001)
        
    def run_backtest(self, signals: List[Dict], data: pd.DataFrame) -> Dict:
        """
        Быстрый бэктест с минимальными накладными расходами.
        
        Returns:
            {"success": bool, "trades": [...], "metrics": {...}}
        """
        try:
            trades = []
            balance = self.initial_balance
            position = None
            position_size = 0
            entry_price = 0
            
            # Создаем индекс сигналов для быстрого поиска
            signals_dict = {sig['timestamp']: sig for sig in signals}
            
            for timestamp, row in data.iterrows():
                signal_data = signals_dict.get(timestamp)
                
                if signal_data:
                    signal_type = signal_data['signal']
                    price = float(row['Close'])
                    
                    if signal_type in ['LONG_ENTRY', 'SHORT_ENTRY'] and position is None:
                        # Открываем позицию
                        position = 'LONG' if signal_type == 'LONG_ENTRY' else 'SHORT'
                        position_size = (balance * 0.02) / price  # 2% от баланса
                        entry_price = price
                        balance -= position_size * price * (1 + self.commission)
                        
                    elif signal_type in ['LONG_EXIT', 'SHORT_EXIT'] and position is not None:
                        # Закрываем позицию
                        exit_price = price

                        profit = 0.0
                        commission_cost = 0.0
                        
                        if position == 'LONG':
                            profit = (exit_price - entry_price) * position_size
                        elif position == 'SHORT':
                            profit = (entry_price - exit_price) * position_size

                        # Комиссия с обеих сторон
                        commission_cost = (entry_price + exit_price) * position_size * self.commission

                        # Итоговый баланс
                        balance += profit - commission_cost
                        
                        # Записываем сделку
                        trades.append({
                            'entry_time': timestamp,  # Упрощаем - используем время выхода
                            'exit_time': timestamp,
                            'direction': position,
                            'entry_price': entry_price,
                            'exit_price': exit_price,
                            'size': position_size,
                            'profit': profit,
                            'commission': position_size * entry_price * self.commission * 2
                        })
                        
                        position = None
                        position_size = 0
                        entry_price = 0
            
            # Базовые метрики
            total_profit = sum(t['profit'] for t in trades)
            winning_trades = sum(1 for t in trades if t['profit'] > 0)
            total_trades = len(trades)
            
            metrics = {
                'total_profit': total_profit,
                'total_trades': total_trades,
                'winning_trades': winning_trades,
                'win_rate': (winning_trades / total_trades) if total_trades > 0 else 0,
                'final_balance': balance + total_profit,
                'return_pct': ((balance + total_profit) / self.initial_balance - 1) * 100
            }
            
            return {
                'success': True,
                'trades': trades,
                'metrics': metrics
            }
            
        except Exception as e:
            return {
                'success': False,
                'trades': [],
                'metrics': {},
                'error': str(e)
            }


class DynamicStrategyRunner:
    """
    Запускает бэктесты сгенерированных стратегий без создания файлов.
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.DynamicStrategyRunner")
        
    def run_backtest(self, signals: List[Dict], data: pd.DataFrame) -> Dict:
        """
        Запускает бэктест с готовыми сигналами.
        
        Returns:
            {"success": bool, "trades": [...], "error": str}
        """
        try:
            # Создаём временную стратегию
            temp_strategy = self._create_temp_strategy(signals)
            
            # Конфигурация для бэктеста
            bot_config = {
                "bot_name": f"discovery_test_{int(time.time())}",
                "strategy_file": "dummy",  # Любое значение, переопределим ниже
                "symbol": self.config['data_settings']['default_ticker'],
                "risk_config_file": '../configs/live_default.json',
                "generate_chart": False
            }
            
            # Создаём наследника Playground который может работать с готовой стратегией
            class CustomPlayground(Playground):
                def __init__(self, ohlcv_data, bot_config, bot_name, custom_strategy=None):
                    self.custom_strategy = custom_strategy
                    super().__init__(ohlcv_data, bot_config, bot_name)
                    
                def _prepare_strategy(self):
                    # Переопределяем метод чтобы использовать кастомную стратегию
                    if self.custom_strategy:
                        return self.custom_strategy
                    else:
                        return super()._prepare_strategy()
            
            # Запускаем бэктест
            backtest = CustomPlayground(
                ohlcv_data=data,
                bot_config=bot_config,
                bot_name=bot_config["bot_name"],
                custom_strategy=temp_strategy
            )
            backtest.run()
            
            # Получаем результаты
            trade_history = backtest.risk_manager.performance_tracker.trade_history
            trade_dicts = [trade.__dict__ for trade in trade_history]
            
            return {
                'success': True,
                'trades': trade_dicts
            }
            
        except Exception as e:
            return {
                'success': False,
                'trades': [],
                'error': str(e)
            }
    
    def _create_temp_strategy(self, signals: List[Dict]):
        """Создает временную стратегию из сигналов."""
        
        class TempStrategy:
            def __init__(self, signals_list):
                self.signals = {sig['timestamp']: sig for sig in signals_list}
            
            def analyze(self, data):
                """
                Метод который ожидает Playground.
                Возвращает словарь с сигналом.
                """
                current_time = data.index[-1]
                signal_data = self.signals.get(current_time)
                if signal_data:
                    signal_type = signal_data['signal']
                    price = signal_data['price']
                    
                    # Преобразуем наши сигналы в формат который понимает Playground
                    if signal_type in ['LONG_ENTRY', 'SHORT_ENTRY']:
                        return {
                            'signal': 'buy',
                            'target_tp_price': price * 1.02  # 2% прибыль
                        }
                
                # Ни одного сигнала - возвращаем None
                return None
        
        return TempStrategy(signals)


class EvolutionaryStrategyDiscovery:
    """
    Главный класс для поиска стратегий через эволюционные алгоритмы.
    """
    
    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        self.logger = self._setup_logging()
        
        # Инициализация компонентов
        self.objective = StrategyDiscoveryObjective(self.config)
        self.indicator_pool = self._build_indicator_pool()
        
        # Статистика эволюции
        self.generation_stats = []
        self.best_ever_individual = None
        self.best_ever_score = -float('inf')
        
        self.logger.info(f"✅ Система поиска стратегий инициализирована")
        self.logger.info(f"📊 Загружено индикаторов: {len(self.indicator_pool)}")
        self.logger.info(f"⚡ Количество процессов для параллелизации: {self.config.get('performance', {}).get('max_workers', mp.cpu_count())}")
        
    def _load_config(self, path: str) -> Dict:
        """Загружает конфигурацию."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            raise FileNotFoundError(f"Конфиг не найден: {path}")
    
    def _setup_logging(self) -> logging.Logger:
        """Настройка логирования."""
        level = getattr(logging, self.config['logging']['level'])
        logging.basicConfig(
            level=level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            handlers=[logging.StreamHandler()]
        )
        return logging.getLogger(__name__)
    
    def _build_indicator_pool(self) -> Dict:
        """Строит пул доступных индикаторов."""
        pool = {}
        enabled_indicators = self.config['indicators']['enabled_indicators']
        
        for indicator in enabled_indicators:
            try:
                if hasattr(talib, indicator.upper()):
                    pool[indicator] = self.config['indicators']['parameters'].get(
                        indicator, 
                        self._get_default_params(indicator)
                    )
            except Exception as e:
                self.logger.warning(f"Не удалось загрузить {indicator}: {e}")
        
        return pool
    
    def _get_default_params(self, indicator: str) -> Dict:
        """Возвращает параметры по умолчанию для индикатора."""
        defaults = {
            'RSI': {'timeperiod': {'min': 10, 'max': 30, 'type': 'int'}},
            'MACD': {'fastperiod': {'min': 8, 'max': 15, 'type': 'int'}, 'slowperiod': {'min': 20, 'max': 30, 'type': 'int'}, 'signalperiod': {'min': 7, 'max': 12, 'type': 'int'}},
            'SMA': {'timeperiod': {'min': 10, 'max': 50, 'type': 'int'}},
            'EMA': {'timeperiod': {'min': 10, 'max': 50, 'type': 'int'}},
            'BBANDS': {'timeperiod': {'min': 15, 'max': 25, 'type': 'int'}, 'nbdevup': {'min': 1.5, 'max': 2.5, 'type': 'float'}, 'nbdevdn': {'min': 1.5, 'max': 2.5, 'type': 'float'}},
            'STOCH': {'fastk_period': {'min': 10, 'max': 20, 'type': 'int'}, 'slowk_period': {'min': 3, 'max': 10, 'type': 'int'}, 'slowd_period': {'min': 3, 'max': 10, 'type': 'int'}},
            'ADX': {'timeperiod': {'min': 10, 'max': 20, 'type': 'int'}},
            'CCI': {'timeperiod': {'min': 15, 'max': 25, 'type': 'int'}},
            'MFI': {'timeperiod': {'min': 10, 'max': 20, 'type': 'int'}},
            'WILLR': {'timeperiod': {'min': 10, 'max': 20, 'type': 'int'}},
            'ATR': {'timeperiod': {'min': 10, 'max': 20, 'type': 'int'}},
            'OBV': {},
            'TEMA': {'timeperiod': {'min': 15, 'max': 35, 'type': 'int'}},
            'DEMA': {'timeperiod': {'min': 15, 'max': 35, 'type': 'int'}},
            'KAMA': {'timeperiod': {'min': 15, 'max': 35, 'type': 'int'}}
        }
        return defaults.get(indicator, {})
    
    def generate_individual(self) -> Dict:
        """Генерирует одну особь (стратегию-кандидата)."""
        rules_config = self.config['rule_generation']
        
        # Случайное количество условий
        num_conditions = random.randint(
            rules_config['min_conditions'], 
            rules_config['max_conditions']
        )
        
        # Выбираем случайные индикаторы
        selected_indicators = random.sample(
            list(self.indicator_pool.keys()), 
            min(num_conditions, len(self.indicator_pool))
        )
        
        # Генерируем параметры индикаторов
        indicators = {}
        for indicator in selected_indicators:
            indicators[indicator] = self._generate_indicator_params(indicator)
        
        # Генерируем торговые правила
        trading_rules = self._generate_trading_rules(selected_indicators, num_conditions)
        
        return {
            "indicators": indicators,
            "trading_rules": trading_rules,
            "metadata": {
                "created_at": datetime.now().isoformat(),
                "num_conditions": num_conditions,
                "num_indicators": len(selected_indicators)
            }
        }
    
    def _generate_indicator_params(self, indicator: str) -> Dict:
        """Генерирует случайные параметры для индикатора."""
        param_specs = self.indicator_pool.get(indicator, {})
        params = {}
        
        for param_name, spec in param_specs.items():
            if spec['type'] == 'int':
                params[param_name] = random.randint(spec['min'], spec['max'])
            elif spec['type'] == 'float':
                params[param_name] = random.uniform(spec['min'], spec['max'])
            elif spec['type'] == 'categorical':
                params[param_name] = random.choice(spec['choices'])
        
        return params
    
    def _generate_trading_rules(self, indicators: List[str], num_conditions: int) -> Dict:
        """Генерирует случайные торговые правила."""
        rules_config = self.config['rule_generation']
        
        # Генерируем условия для каждого типа сигнала
        long_entry = self._generate_conditions(indicators, num_conditions, 'long_entry')
        short_entry = self._generate_conditions(indicators, num_conditions, 'short_entry')
        
        # Простые правила выхода (можно усложить)
        long_exit = self._generate_exit_conditions(indicators, 'long_exit')
        short_exit = self._generate_exit_conditions(indicators, 'short_exit')
        
        return {
            'long_entry_conditions': long_entry,
            'long_exit_conditions': long_exit,
            'short_entry_conditions': short_entry,
            'short_exit_conditions': short_exit,
            'logic_operator': random.choice(['AND', 'OR', 'OR']),  # Увеличиваем вероятность OR
            'risk_management': self._generate_risk_rules()
        }
        
    def _generate_exit_conditions(self, indicators: List[str], signal_type: str) -> List[Dict]:
        """Генерирует условия выхода на основе используемых индикаторов."""
        exit_conditions = []
        
        # Приоритетные индикаторы для выхода (в порядке приоритета)
        priority_indicators = ['RSI', 'STOCH_k', 'STOCH_d', 'CCI', 'MFI', 'WILLR']
        
        # Ищем приоритетные индикаторы в списке
        available_priority = [ind for ind in priority_indicators if ind in indicators]
        
        if available_priority:
            # Используем приоритетный индикатор
            indicator = available_priority[0]
            
            if 'long_exit' in signal_type:
                # Выход из лонга - когда перекуплено
                if indicator == 'RSI':
                    threshold = random.uniform(70, 85)
                    operator = '>'
                elif indicator in ['STOCH_k', 'STOCH_d']:
                    threshold = random.uniform(80, 95)
                    operator = '>'
                elif indicator == 'CCI':
                    threshold = random.uniform(100, 200)
                    operator = '>'
                elif indicator == 'MFI':
                    threshold = random.uniform(70, 85)
                    operator = '>'
                elif indicator == 'WILLR':
                    threshold = random.uniform(-20, -10)
                    operator = '>'
                else:
                    threshold = 70
                    operator = '>'
            else:
                # Выход из шорта - когда перепродано
                if indicator == 'RSI':
                    threshold = random.uniform(15, 30)
                    operator = '<'
                elif indicator in ['STOCH_k', 'STOCH_d']:
                    threshold = random.uniform(5, 20)
                    operator = '<'
                elif indicator == 'CCI':
                    threshold = random.uniform(-200, -100)
                    operator = '<'
                elif indicator == 'MFI':
                    threshold = random.uniform(15, 30)
                    operator = '<'
                elif indicator == 'WILLR':
                    threshold = random.uniform(-90, -80)
                    operator = '<'
                else:
                    threshold = 30
                    operator = '<'
            
            exit_conditions.append({
                'type': 'threshold',
                'indicator': indicator,
                'operator': operator,
                'threshold': threshold
            })
        else:
            # Если нет приоритетных, используем любой доступный
            if indicators:
                indicator = random.choice(indicators)
                exit_conditions.append({
                    'type': 'threshold',
                    'indicator': indicator,
                    'operator': '>' if 'long_exit' in signal_type else '<',
                    'threshold': self._generate_threshold_value(indicator, signal_type)
                })
        
        return exit_conditions
    
    def _generate_conditions(self, indicators: List[str], num_conditions: int, signal_type: str) -> List[Dict]:
        """Генерирует условия для определенного типа сигнала."""
        conditions = []
        rules_config = self.config['rule_generation']
        
        for _ in range(min(num_conditions, len(indicators))):
            indicator = random.choice(indicators)
            condition_type = random.choice(['threshold', 'crossover'] if rules_config['enable_crossovers'] else ['threshold'])
            
            if condition_type == 'threshold':
                # Проблема здесь! Используем базовое имя индикатора
                # Но в данных он добавляется с параметрами!
                condition = {
                    'type': 'threshold',
                    'indicator': indicator,  # Например, "RSI" вместо "RSI_14"
                    'operator': random.choice(['>', '<', '>=', '<=']),
                    'threshold': self._generate_threshold_value(indicator, signal_type)
                }
                self.logger.debug(f"Генерируем threshold условие: {condition}")
                
                # Логируем примеры условий каждые 1000 стратегий
                if hasattr(self, 'condition_debug_count'):
                    self.condition_debug_count += 1
                else:
                    self.condition_debug_count = 1
                
                if self.condition_debug_count % 1000 == 1:
                    self.logger.info(f"🔍 Пример условия: {condition['indicator']} {condition['operator']} {condition['threshold']:.2f}")
                
                conditions.append(condition)
            elif condition_type == 'crossover':
                if len(indicators) > 1:
                    other_indicator = random.choice([ind for ind in indicators if ind != indicator])
                    condition = {
                        'type': 'crossover',
                        'indicator1': indicator,
                        'indicator2': other_indicator,
                        'direction': random.choice(['above', 'below'])
                    }
                    self.logger.debug(f"Генерируем crossover условие: {condition}")
                    conditions.append(condition)
        
        return conditions
    
    def _generate_threshold_value(self, indicator: str, signal_type: str) -> float:
        """Генерирует реалистичные пороговые значения для индикаторов."""
        # Реалистичные диапазоны для разных индикаторов
        ranges = {
            'RSI': {
                'long': (20, 45),    # Oversold-neutral зона для входа в лонг
                'short': (55, 80)    # Neutral-overbought для входа в шорт
            },
            'MACD': {
                'long': (-0.01, 0.01),   # Около нуля
                'short': (-0.01, 0.01)
            },
            'SMA': {
                'long': (0.98, 1.02),    # ±2% от текущей цены
                'short': (0.98, 1.02)
            },
            'EMA': {
                'long': (0.95, 1.05),    # ±5% от текущей цены
                'short': (0.95, 1.05)
            },
            'CCI': {
                'long': (-200, 0),       # Oversold зона
                'short': (0, 200)        # Overbought зона
            },
            'WILLR': {
                'long': (-80, -20),      # Williams %R oversold
                'short': (-80, -20)
            },
            'ADX': {
                'long': (20, 40),        # Средний тренд
                'short': (20, 40)
            },
            'MFI': {
                'long': (20, 40),        # Money Flow oversold
                'short': (60, 80)        # Money Flow overbought
            },
            'ATR': {
                'long': (100, 2000),     # Волатильность для BTC
                'short': (100, 2000)
            },
            'STOCH_k': {
                'long': (10, 30),        # Stochastic oversold
                'short': (70, 90)        # Stochastic overbought
            },
            'STOCH_d': {
                'long': (10, 30),
                'short': (70, 90)
            },
            'BB_upper': {
                'long': (0.98, 1.02),    # Относительно цены
                'short': (0.98, 1.02)
            },
            'BB_lower': {
                'long': (0.98, 1.02),
                'short': (0.98, 1.02)
            },
            'BB_middle': {
                'long': (0.98, 1.02),
                'short': (0.98, 1.02)
            }
        }
        
        # Определяем тип сигнала
        signal_key = 'long' if 'long' in signal_type else 'short'
        
        if indicator in ranges:
            range_values = ranges[indicator][signal_key]
            return random.uniform(range_values[0], range_values[1])
        else:
            # Дефолтные безопасные диапазоны
            if 'long' in signal_type:
                return random.uniform(20, 40)  # Низкие значения для лонга
            else:
                return random.uniform(60, 80)  # Высокие значения для шорта
    
    def _generate_risk_rules(self) -> Dict:
        """Генерирует правила риск-менеджмента."""
        risk_config = self.config['risk_management']
        
        # Случайно выбираем либо SL, либо TP (не оба)
        use_stop_loss = random.random() < 0.5
        
        if use_stop_loss:
            return {
                'stop_loss': {
                    'type': random.choice(['fixed', 'trailing']),
                    'value': random.uniform(risk_config['stop_loss_range'][0], risk_config['stop_loss_range'][1])
                },
                'take_profit': {'type': 'none'}
            }
        else:
            return {
                'stop_loss': {'type': 'none'},
                'take_profit': {
                    'type': 'fixed',
                    'value': random.uniform(risk_config['take_profit_range'][0], risk_config['take_profit_range'][1])
                }
            }
    
    def mutate(self, individual: Dict) -> Dict:
        """Мутирует особь (одно изменение на потомка)."""
        mutated = copy.deepcopy(individual)
        mutation_config = self.config['evolution']['mutation']
        
        # Выбираем случайный тип мутации
        mutation_type = random.choice([
            'modify_indicator_param',
            'modify_threshold',
            'change_logic_operator',
            'modify_risk_rules'
        ])
        
        if mutation_type == 'modify_indicator_param':
            self._mutate_indicator_param(mutated)
        elif mutation_type == 'modify_threshold':
            self._mutate_threshold(mutated)
        elif mutation_type == 'change_logic_operator':
            self._mutate_logic_operator(mutated)
        elif mutation_type == 'modify_risk_rules':
            self._mutate_risk_rules(mutated)
        
        return mutated
    
    def _mutate_indicator_param(self, individual: Dict):
        """Мутирует параметр индикатора."""
        if not individual['indicators']:
            return
        
        indicator = random.choice(list(individual['indicators'].keys()))
        params = individual['indicators'][indicator]
        
        if params:
            param_name = random.choice(list(params.keys()))
            param_spec = self.indicator_pool.get(indicator, {}).get(param_name, {})
            
            if param_spec.get('type') == 'int':
                current_value = params[param_name]
                step = random.choice([-1, 1])
                new_value = max(param_spec['min'], min(param_spec['max'], current_value + step))
                params[param_name] = new_value
            elif param_spec.get('type') == 'float':
                current_value = params[param_name]
                step = random.uniform(-0.1, 0.1)
                new_value = max(param_spec['min'], min(param_spec['max'], current_value + step))
                params[param_name] = round(new_value, 3)
    
    def _mutate_threshold(self, individual: Dict):
        """Мутирует пороговое значение в условиях."""
        rules = individual['trading_rules']
        all_conditions = (
            rules.get('long_entry_conditions', []) +
            rules.get('short_entry_conditions', []) +
            rules.get('long_exit_conditions', []) +
            rules.get('short_exit_conditions', [])
        )
        
        threshold_conditions = [c for c in all_conditions if c.get('type') == 'threshold']
        if threshold_conditions:
            condition = random.choice(threshold_conditions)
            current_threshold = condition['threshold']
            # Мутируем в пределах ±10%
            mutation_factor = random.uniform(0.9, 1.1)
            condition['threshold'] = round(current_threshold * mutation_factor, 3)
    
    def _mutate_logic_operator(self, individual: Dict):
        """Мутирует логический оператор."""
        individual['trading_rules']['logic_operator'] = random.choice(['AND', 'OR'])
    
    def _mutate_risk_rules(self, individual: Dict):
        """Мутирует правила риск-менеджмента."""
        individual['trading_rules']['risk_management'] = self._generate_risk_rules()
    
    def crossover(self, parent1: Dict, parent2: Dict) -> Tuple[Dict, Dict]:
        """Скрещивает двух родителей."""
        child1 = copy.deepcopy(parent1)
        child2 = copy.deepcopy(parent2)
        
        # Скрещивание индикаторов
        self._crossover_indicators(child1, child2, parent1, parent2)
        
        # Скрещивание торговых правил
        if random.random() < 0.5:
            child1['trading_rules'], child2['trading_rules'] = child2['trading_rules'], child1['trading_rules']
        
        return child1, child2
    
    def _crossover_indicators(self, child1: Dict, child2: Dict, parent1: Dict, parent2: Dict):
        """Скрещивает индикаторы между родителями."""
        p1_indicators = set(parent1['indicators'].keys())
        p2_indicators = set(parent2['indicators'].keys())
        common_indicators = p1_indicators & p2_indicators
        
        # Обмениваемся общими индикаторами
        for indicator in common_indicators:
            if random.random() < 0.5:
                child1['indicators'][indicator], child2['indicators'][indicator] = \
                    child2['indicators'][indicator], child1['indicators'][indicator]
    
    def run_evolution(self, data: pd.DataFrame) -> Dict:
        """Запускает полный процесс эволюционного поиска."""
        evolution_config = self.config['evolution']
        population_size = evolution_config['population_size']
        num_generations = evolution_config['generations']
        
        self.logger.info("🧬 Запуск эволюционного поиска стратегий")
        self.logger.info(f"📊 Популяция: {population_size}, Поколения: {num_generations}")
        # Проверяем настройки производительности
        max_workers = self.config.get('performance', {}).get('max_workers', mp.cpu_count())
        self.logger.info(f"⚡ Параллельная обработка: {max_workers} процессов")
        
        # Инициализация популяции
        population = [self.generate_individual() for _ in range(population_size)]
        
        start_time = time.time()
        
        with tqdm(total=num_generations, desc="Эволюция поколений") as pbar:
            for generation in range(num_generations):
                gen_start_time = time.time()
                
                self.logger.info(f"🧬 Начинаем поколение {generation}: генерация и оценка {population_size} стратегий")
                
                # Оценка популяции (параллельно)
                fitness_scores = []
                successful_individuals = 0
                
                # Определяем количество процессов (по умолчанию - количество ядер)
                max_workers = self.config.get('performance', {}).get('max_workers', mp.cpu_count())
                self.logger.info(f"  🚀 Параллельная оценка {population_size} особей на {max_workers} процессах")
                
                # Подготавливаем данные для передачи в процессы
                data_dict = {
                    'data': data.to_dict('records'),
                    'index': data.index.astype(str).tolist()
                }
                
                # Параллельная обработка
                with ProcessPoolExecutor(max_workers=max_workers) as executor:
                    # Отправляем задачи
                    future_to_index = {
                        executor.submit(evaluate_individual_worker, individual, self.config, data_dict): i
                        for i, individual in enumerate(population)
                    }
                    
                    # Собираем результаты
                    fitness_scores = [0] * len(population)  # Инициализируем список
                    completed = 0
                    
                    for future in as_completed(future_to_index):
                        index = future_to_index[future]
                        try:
                            result = future.result()
                            fitness_scores[index] = result['score']
                            if result['success']:
                                successful_individuals += 1
                                
                            # Логируем прогресс
                            completed += 1
                            if completed % 20 == 0:  # Логируем каждые 20 завершенных
                                self.logger.info(f"  📊 Завершено {completed}/{population_size} оценок")
                                
                        except Exception as e:
                            self.logger.warning(f"  ⚠️ Ошибка оценки особи {index}: {e}")
                            fitness_scores[index] = self.config['scoring']['penalties']['critical_error']
                
                # Обновляем лучшую особь
                best_idx = fitness_scores.index(max(fitness_scores))
                if fitness_scores[best_idx] > self.best_ever_score:
                    self.best_ever_score = fitness_scores[best_idx]
                    self.best_ever_individual = copy.deepcopy(population[best_idx])
                
                # Статистика поколения
                gen_stats = {
                    'generation': generation,
                    'best_score': max(fitness_scores),
                    'avg_score': np.mean(fitness_scores),
                    'successful_individuals': successful_individuals,
                    'population_size': len(population),
                    'duration': time.time() - gen_start_time
                }
                self.generation_stats.append(gen_stats)
                
                # Проверка на провал поколения
                if successful_individuals == 0:
                    self.logger.warning(f"⚠️ Поколение {generation}: все особи провалились, генерируем новую популяцию")
                    population = [self.generate_individual() for _ in range(population_size)]
                else:
                    # Селекция и воспроизводство
                    population = self._evolve_population(population, fitness_scores)
                
                # Обновление прогресса
                elapsed_time = time.time() - start_time
                remaining_time = (elapsed_time / (generation + 1)) * (num_generations - generation - 1)
                
                pbar.set_postfix({
                    'Лучший': f'{max(fitness_scores):.3f}',
                    'Успешных': f'{successful_individuals}/{population_size}',
                    'ETA': f'{timedelta(seconds=int(remaining_time))}'
                })
                pbar.update(1)
                
                # Подробное логирование
                self.logger.info(
                    f"Поколение {generation:2d}: "
                    f"лучший={max(fitness_scores):.3f}, "
                    f"средний={np.mean(fitness_scores):.3f}, "
                    f"успешных={successful_individuals}/{population_size}"
                )
        
        total_duration = time.time() - start_time
        
        # Формируем результаты
        results = {
            'best_individual': self.best_ever_individual,
            'best_score': self.best_ever_score,
            'generation_stats': self.generation_stats,
            'total_duration_minutes': total_duration / 60,
            'total_evaluations': self.objective.evaluation_count,
            'successful_evaluations': self.objective.successful_evaluations,
            'success_rate': self.objective.successful_evaluations / self.objective.evaluation_count if self.objective.evaluation_count > 0 else 0,
            'timestamp': datetime.now().isoformat()
        }
        
        self.logger.info(f"🎉 Эволюция завершена за {total_duration/60:.1f} минут")
        self.logger.info(f"🏆 Лучший результат: {self.best_ever_score:.3f}")
        
        return results
    
    def _evolve_population(self, population: List[Dict], fitness_scores: List[float]) -> List[Dict]:
        """Эволюционирует популяцию (селекция + воспроизводство)."""
        evolution_config = self.config['evolution']
        
        # Сортируем по фитнесу
        sorted_pop = sorted(zip(population, fitness_scores), key=lambda x: x[1], reverse=True)
        
        # Элитизм - сохраняем лучших
        elite_size = int(len(population) * evolution_config['elite_ratio'])
        elite = [individual for individual, _ in sorted_pop[:elite_size]]
        
        # Генерируем новое поколение
        new_population = elite.copy()
        
        while len(new_population) < len(population):
            # Турнирная селекция
            parent1 = self._tournament_selection(sorted_pop, evolution_config['tournament_size'])
            parent2 = self._tournament_selection(sorted_pop, evolution_config['tournament_size'])
            
            # Скрещивание
            if random.random() < evolution_config['crossover_rate']:
                child1, child2 = self.crossover(parent1, parent2)
            else:
                child1, child2 = copy.deepcopy(parent1), copy.deepcopy(parent2)
            
            # Мутация
            if random.random() < evolution_config['mutation_rate']:
                child1 = self.mutate(child1)
            if random.random() < evolution_config['mutation_rate']:
                child2 = self.mutate(child2)
            
            new_population.extend([child1, child2])
        
        return new_population[:len(population)]
    
    def _tournament_selection(self, sorted_population: List[Tuple], tournament_size: int) -> Dict:
        """Турнирная селекция."""
        tournament = random.sample(sorted_population, min(tournament_size, len(sorted_population)))
        winner = max(tournament, key=lambda x: x[1])
        return winner[0]
    
    def save_results(self, results: Dict):
        """Сохраняет результаты эволюции."""
        save_config = self.config['saving']
        
        # Создаем директории
        strategy_dir = Path(save_config['strategy_dir'])
        config_dir = Path(save_config['config_dir'])
        results_dir = Path(save_config['results_dir'])
        
        for directory in [strategy_dir, config_dir, results_dir]:
            directory.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # Сохраняем лучшую стратегию
        if results['best_individual']:
            strategy_name = f"evolved_strategy_{timestamp}"
            
            # Конфиг стратегии
            config_path = config_dir / f"{strategy_name}.json"
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(results['best_individual'], f, indent=2, ensure_ascii=False)
            
            # Код стратегии
            strategy_code = self._generate_strategy_code(results['best_individual'], strategy_name)
            strategy_path = strategy_dir / f"{strategy_name}.py"
            with open(strategy_path, 'w', encoding='utf-8') as f:
                f.write(strategy_code)
            
            self.logger.info(f"💾 Стратегия сохранена: {strategy_path}")
            self.logger.info(f"📋 Конфиг сохранен: {config_path}")
        
        # Сохраняем полные результаты
        results_path = results_dir / f"evolution_results_{timestamp}.json"
        with open(results_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)
        
        self.logger.info(f"📊 Результаты сохранены: {results_path}")
    
    def _generate_strategy_code(self, individual: Dict, strategy_name: str) -> str:
        """Генерирует код стратегии."""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        code = f'''# Файл: {strategy_name}.py
# Автоматически сгенерированная стратегия
# Создана эволюционным алгоритмом: {timestamp}
# Оценка стратегии: {self.best_ever_score:.3f}

import pandas as pd
import talib
from typing import Dict, Any


class {strategy_name.title().replace('_', '')}Strategy:
    """
    Эволюционно найденная стратегия.
    
    Индикаторы: {', '.join(individual['indicators'].keys())}
    Условий в правилах: {individual['metadata']['num_conditions']}
    """
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.indicators = {individual['indicators']}
        self.trading_rules = {individual['trading_rules']}
        self.current_position = None
    
    def add_indicators(self, data: pd.DataFrame) -> pd.DataFrame:
        """Добавляет индикаторы к данным."""
        enriched_data = data.copy()
        
        # Подготавливаем основные массивы
        close = data['Close'].values
        high = data['High'].values
        low = data['Low'].values
        volume = data['Volume'].values if 'Volume' in data.columns else None
        
        for indicator_name, params in self.indicators.items():
            try:
                if hasattr(talib, indicator_name.upper()):
                    indicator_func = getattr(talib, indicator_name.upper())
                    
                    if indicator_name.upper() == 'RSI':
                        timeperiod = params.get('timeperiod', 14)
                        result = indicator_func(close, timeperiod=timeperiod)
                        enriched_data['RSI'] = result
                    
                    elif indicator_name.upper() == 'MACD':
                        macd, macdsignal, macdhist = indicator_func(
                            close, 
                            fastperiod=params.get('fastperiod', 12),
                            slowperiod=params.get('slowperiod', 26),
                            signalperiod=params.get('signalperiod', 9)
                        )
                        enriched_data['MACD'] = macd
                        enriched_data['MACD_signal'] = macdsignal
                        enriched_data['MACD_hist'] = macdhist
                    
                    elif indicator_name.upper() == 'SMA':
                        timeperiod = params.get('timeperiod', 20)
                        result = indicator_func(close, timeperiod=timeperiod)
                        enriched_data['SMA'] = result
                    
                    elif indicator_name.upper() == 'EMA':
                        timeperiod = params.get('timeperiod', 20)
                        result = indicator_func(close, timeperiod=timeperiod)
                        enriched_data['EMA'] = result
                    
                    elif indicator_name.upper() == 'BBANDS':
                        upper, middle, lower = indicator_func(
                            close,
                            timeperiod=params.get('timeperiod', 20),
                            nbdevup=params.get('nbdevup', 2),
                            nbdevdn=params.get('nbdevdn', 2)
                        )
                        enriched_data['BB_upper'] = upper
                        enriched_data['BB_middle'] = middle
                        enriched_data['BB_lower'] = lower
                    
                    # Можно добавить другие индикаторы по аналогии
                    
            except Exception as e:
                print(f"Ошибка добавления индикатора: {{e}}")
        
        return enriched_data
    
    def generate_signals(self, data: pd.DataFrame) -> str:
        """
        Генерирует торговые сигналы.
        
        Returns:
            str: "LONG_ENTRY", "LONG_EXIT", "SHORT_ENTRY", "SHORT_EXIT", "HOLD"
        """
        if len(data) < 20:  # Минимум данных для индикаторов
            return "HOLD"
        
        enriched_data = self.add_indicators(data)
        current_row = enriched_data.iloc[-1]
        
        # Проверяем условия выхода (приоритет)
        if self.current_position == "LONG":
            if self._check_conditions(self.trading_rules['long_exit_conditions'], current_row, enriched_data):
                self.current_position = None
                return "LONG_EXIT"
        elif self.current_position == "SHORT":
            if self._check_conditions(self.trading_rules['short_exit_conditions'], current_row, enriched_data):
                self.current_position = None
                return "SHORT_EXIT"
        
        # Проверяем условия входа (только если нет позиции)
        if self.current_position is None:
            if self._check_conditions(self.trading_rules['long_entry_conditions'], current_row, enriched_data):
                self.current_position = "LONG"
                return "LONG_ENTRY"
            elif self._check_conditions(self.trading_rules['short_entry_conditions'], current_row, enriched_data):
                self.current_position = "SHORT"
                return "SHORT_ENTRY"
        
        return "HOLD"
    
    def _check_conditions(self, conditions: list, current_row: pd.Series, data: pd.DataFrame) -> bool:
        """Проверяет список условий."""
        if not conditions:
            return False
        
        results = []
        for condition in conditions:
            result = self._evaluate_condition(condition, current_row, data)
            results.append(result)
        
        logic_op = self.trading_rules.get('logic_operator', 'AND')
        if logic_op == 'AND':
            return all(results)
        else:
            return any(results)
    
    def _evaluate_condition(self, condition: dict, current_row: pd.Series, data: pd.DataFrame) -> bool:
        """Оценивает одно условие."""
        try:
            if condition['type'] == 'threshold':
                indicator = condition['indicator']
                operator = condition['operator']
                threshold = condition['threshold']
                
                if indicator not in current_row or pd.isna(current_row[indicator]):
                    return False
                
                value = current_row[indicator]
                
                if operator == '>':
                    return value > threshold
                elif operator == '<':
                    return value < threshold
                elif operator == '>=':
                    return value >= threshold
                elif operator == '<=':
                    return value <= threshold
                else:
                    return False
            
            elif condition['type'] == 'crossover':
                # Упрощенная проверка кроссовера
                if len(data) < 2:
                    return False
                
                ind1 = condition['indicator1']
                ind2 = condition['indicator2']
                direction = condition.get('direction', 'above')
                
                if ind1 not in data.columns or ind2 not in data.columns:
                    return False
                
                current_val1 = data.iloc[-1][ind1]
                current_val2 = data.iloc[-1][ind2]
                prev_val1 = data.iloc[-2][ind1]
                prev_val2 = data.iloc[-2][ind2]
                
                if any(pd.isna([current_val1, current_val2, prev_val1, prev_val2])):
                    return False
                
                if direction == 'above':
                    return prev_val1 <= prev_val2 and current_val1 > current_val2
                elif direction == 'below':
                    return prev_val1 >= prev_val2 and current_val1 < current_val2
            
            return False
        
        except Exception as e:
            print(f"Ошибка оценки условия {{condition}}: {{e}}")
            return False
'''
        
        return code


def main():
    """Главная функция для запуска поиска стратегий."""
    print("🧬 Запуск системы поиска стратегий через эволюцию")
    
    # Загружаем конфигурацию
    config_path = Path(__file__).parent / "discovery_config.json"
    
    try:
        discovery = EvolutionaryStrategyDiscovery(str(config_path))
        
        # Загружаем данные
        data_config = discovery.config['data_settings']
        print(f"📈 Загрузка данных: {data_config['default_ticker']}")
        
        data = yf.download(
            tickers=data_config['default_ticker'],
            period=data_config['default_period'],
            interval=data_config['default_interval'],
            auto_adjust=True,
            progress=False
        )
        
        # Исправляем проблему с мультииндексными колонками
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.droplevel(1)
        
        if data is None or data.empty:
            raise ValueError("Не удалось загрузить данные")
        
        print(f"✅ Данные загружены: {len(data)} свечей")
        
        # Запускаем эволюцию
        results = discovery.run_evolution(data)
        
        # Сохраняем результаты
        discovery.save_results(results)
        
        # Финальная статистика
        print("\n" + "="*60)
        print("🎉 ПОИСК СТРАТЕГИЙ ЗАВЕРШЕН")
        print("="*60)
        print(f"🏆 Лучшая оценка: {results['best_score']:.3f}")
        print(f"⏱️ Время выполнения: {results['total_duration_minutes']:.1f} минут")
        print(f"📊 Всего оценок: {results['total_evaluations']}")
        print(f"✅ Успешных оценок: {results['successful_evaluations']} ({results['success_rate']*100:.1f}%)")
        
        if results['best_individual']:
            best = results['best_individual']
            print(f"🔧 Индикаторов в лучшей стратегии: {len(best['indicators'])}")
            print(f"📋 Условий в правилах: {best['metadata']['num_conditions']}")
            print("📁 Файлы стратегии сохранены в папки strategies/new и configs/new")
        
    except Exception as e:
        print(f"❌ Критическая ошибка: {e}")
        raise


if __name__ == "__main__":
    main()