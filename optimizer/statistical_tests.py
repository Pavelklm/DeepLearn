# Файл: optimizer/statistical_tests.py

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Any
import logging
from scipy import stats
from scipy.stats import jarque_bera, shapiro, kstest, ttest_ind
import warnings
warnings.filterwarnings('ignore', category=RuntimeWarning)


class StatisticalValidator:
    """
    Модуль статистической валидации результатов торговых стратегий.
    
    Включает:
    1. Тесты статистической значимости
    2. Анализ распределения доходностей
    3. Bootstrap анализ
    4. Тесты на случайность
    5. Анализ автокорреляции
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.significance_level = config['validation']['statistical_significance_level']
        self.min_trades = config['validation']['min_trades_for_significance']
    
    def validate_trades(self, trades: List[Dict]) -> bool:
        """
        Комплексная статистическая валидация сделок.
        
        Args:
            trades: Список сделок
            
        Returns:
            bool: True если стратегия статистически значима
        """
        if len(trades) < self.min_trades:
            self.logger.debug(f"Недостаточно сделок для статистического анализа: {len(trades)}")
            return False
        
        try:
            # Извлекаем доходности
            returns = np.array([trade['profit'] for trade in trades])
            
            # Базовые тесты
            basic_tests = self._run_basic_tests(returns)
            normality_tests = self._test_normality(returns)
            randomness_tests = self._test_randomness(returns)
            
            # Считаем что стратегия валидна если проходит базовые тесты
            # и хотя бы один из дополнительных
            valid = (basic_tests['significant_positive_mean'] and 
                    basic_tests['reasonable_variance'] and
                    (randomness_tests['passes_runs_test'] or 
                     not normality_tests['clearly_non_normal']))
            
            if valid:
                self.logger.debug("Стратегия прошла статистическую валидацию")
            else:
                self.logger.debug("Стратегия не прошла статистическую валидацию")
            
            return valid
            
        except Exception as e:
            self.logger.error(f"Ошибка в статистической валидации: {e}")
            return False
    
    def _run_basic_tests(self, returns: np.ndarray) -> Dict:
        """Базовые статистические тесты."""
        results = {}
        
        # 1. Тест на положительное математическое ожидание
        mean_return = np.mean(returns)
        std_return = np.std(returns, ddof=1)
        n = len(returns)
        
        # t-тест для среднего
        t_stat = mean_return / (std_return / np.sqrt(n))
        p_value_mean = 1 - stats.t.cdf(t_stat, df=n-1)  # Односторонний тест
        
        results['mean_return'] = mean_return
        results['t_statistic'] = t_stat
        results['p_value_mean'] = p_value_mean
        results['significant_positive_mean'] = p_value_mean < self.significance_level
        
        # 2. Тест на разумность дисперсии
        # Проверяем что коэффициент вариации не слишком высокий
        cv = abs(std_return / mean_return) if mean_return != 0 else float('inf')
        results['coefficient_of_variation'] = cv
        results['reasonable_variance'] = cv < 5.0  # Эмпирический порог
        
        # 3. Тест на outliers (модифицированный z-score)
        mad = np.median(np.abs(returns - np.median(returns)))
        modified_z_scores = 0.6745 * (returns - np.median(returns)) / mad if mad > 0 else np.zeros_like(returns)
        outliers = np.abs(modified_z_scores) > 3.5
        outlier_pct = np.sum(outliers) / len(returns)
        
        results['outlier_percentage'] = outlier_pct
        results['reasonable_outliers'] = outlier_pct < 0.1  # Менее 10% outliers
        
        return results
    
    def _test_normality(self, returns: np.ndarray) -> Dict:
        """Тесты на нормальность распределения доходностей."""
        results = {}
        n = len(returns)
        
        try:
            # 1. Тест Шапиро-Уилка (для малых выборок)
            if n <= 5000:
                shapiro_stat, shapiro_p = shapiro(returns)
                results['shapiro_statistic'] = shapiro_stat
                results['shapiro_p_value'] = shapiro_p
                results['shapiro_normal'] = shapiro_p > self.significance_level
            else:
                results['shapiro_normal'] = None  # Не применим для больших выборок
            
            # 2. Тест Жарка-Бера
            jb_stat, jb_p = jarque_bera(returns)
            results['jarque_bera_statistic'] = jb_stat
            results['jarque_bera_p_value'] = jb_p
            results['jarque_bera_normal'] = jb_p > self.significance_level
            
            # 3. Тест Колмогорова-Смирнова с нормальным распределением
            # Сравниваем с нормальным распределением с теми же параметрами
            mean_r = float(np.mean(returns))
            std_r = float(np.std(returns))
            ks_stat, ks_p = kstest(returns, "norm", args=(float(mean_r), float(std_r)))   # type: ignore
            results['ks_statistic'] = ks_stat
            results['ks_p_value'] = ks_p
            results['ks_normal'] = ks_p > self.significance_level
            
            # Общий вывод о нормальности
            normal_tests = [
                results.get('shapiro_normal'),
                results['jarque_bera_normal'],
                results['ks_normal']
            ]
            normal_tests = [t for t in normal_tests if t is not None]
            
            if normal_tests:
                results['likely_normal'] = sum(normal_tests) >= len(normal_tests) // 2
                results['clearly_non_normal'] = not any(normal_tests)
            else:
                results['likely_normal'] = False
                results['clearly_non_normal'] = True
                
        except Exception as e:
            self.logger.debug(f"Ошибка в тестах нормальности: {e}")
            results['likely_normal'] = False
            results['clearly_non_normal'] = True
        
        return results
    
    def _test_randomness(self, returns: np.ndarray) -> Dict:
        """Тесты на случайность последовательности доходностей."""
        results = {}
        
        try:
            # 1. Runs test (тест серий)
            # Преобразуем доходности в бинарную последовательность (прибыль/убыток)
            binary_sequence = (returns > 0).astype(int)
            
            runs_result = self._runs_test(binary_sequence)
            results.update(runs_result)
            
            # 2. Тест автокорреляции
            autocorr_result = self._test_autocorrelation(returns)
            results.update(autocorr_result)
            
            # 3. Тест на кластеризацию волатильности (ARCH эффект)
            arch_result = self._test_arch_effect(returns)
            results.update(arch_result)
            
            # Общий вывод о случайности
            randomness_indicators = [
                results.get('passes_runs_test', False),
                results.get('no_significant_autocorr', False),
                not results.get('has_arch_effect', True)
            ]
            
            results['appears_random'] = sum(randomness_indicators) >= 2
            
        except Exception as e:
            self.logger.debug(f"Ошибка в тестах случайности: {e}")
            results['appears_random'] = False
            results['passes_runs_test'] = False
        
        return results
    
    def _runs_test(self, binary_sequence: np.ndarray) -> Dict:
        """
        Runs test для проверки случайности последовательности.
        
        Тестирует H0: последовательность случайна
        """
        n = len(binary_sequence)
        
        # Подсчитываем количество единиц и нулей
        n1 = np.sum(binary_sequence)  # Количество прибыльных сделок
        n0 = n - n1  # Количество убыточных сделок
        
        if n1 == 0 or n0 == 0:
            # Все сделки одинаковые - явно не случайно
            return {
                'runs_count': 1,
                'expected_runs': 1,
                'runs_z_score': 0,
                'runs_p_value': 0,
                'passes_runs_test': False
            }
        
        # Подсчитываем количество серий (runs)
        runs = 1
        for i in range(1, n):
            if binary_sequence[i] != binary_sequence[i-1]:
                runs += 1
        
        # Ожидаемое количество серий при случайной последовательности
        expected_runs = (2 * n1 * n0) / n + 1
        
        # Дисперсия количества серий
        variance_runs = (2 * n1 * n0 * (2 * n1 * n0 - n)) / (n**2 * (n - 1))
        
        if variance_runs <= 0:
            return {
                'runs_count': runs,
                'expected_runs': expected_runs,
                'runs_z_score': 0,
                'runs_p_value': 1,
                'passes_runs_test': True
            }
        
        # Z-статистика
        z_score = (runs - expected_runs) / np.sqrt(variance_runs)
        
        # p-value для двустороннего теста
        p_value = 2 * (1 - stats.norm.cdf(abs(z_score)))
        
        return {
            'runs_count': runs,
            'expected_runs': expected_runs,
            'runs_variance': variance_runs,
            'runs_z_score': z_score,
            'runs_p_value': p_value,
            'passes_runs_test': p_value > self.significance_level
        }
    
    def _test_autocorrelation(self, returns: np.ndarray, max_lags: int = 5) -> Dict:
        """Тест на автокорреляцию доходностей."""
        n = len(returns)
        max_lags = min(max_lags, n // 4)  # Не более четверти от размера выборки
        
        results: Dict[str, Any] = {
            'autocorrelations': {},
            'ljung_box_statistics': {},
            'ljung_box_p_values': {}
        }
        
        significant_lags = []
        
        for lag in range(1, max_lags + 1):
            try:
                # Рассчитываем автокорреляцию
                autocorr = np.corrcoef(returns[:-lag], returns[lag:])[0, 1]
                
                if np.isfinite(autocorr):
                    results['autocorrelations'][lag] = autocorr
                    
                    # Тест значимости автокорреляции
                    # Стандартная ошибка для автокорреляции при нулевой гипотезе
                    se = 1 / np.sqrt(n)
                    
                    # Проверяем значимость
                    if abs(autocorr) > 1.96 * se:  # 95% доверительный интервал
                        significant_lags.append(lag)
                
                # Тест Льюнга-Бокса для данного лага
                # Упрощенная версия
                lb_stat = n * (n + 2) * autocorr**2 / (n - lag)
                lb_p = 1 - stats.chi2.cdf(lb_stat, df=1)
                
                results['ljung_box_statistics'][lag] = lb_stat
                results['ljung_box_p_values'][lag] = lb_p
                
            except Exception as e:
                self.logger.debug(f"Ошибка в расчете автокорреляции для лага {lag}: {e}")
                continue
        
        results['significant_autocorr_lags'] = significant_lags
        results['no_significant_autocorr'] = len(significant_lags) == 0
        
        return results
    
    def _test_arch_effect(self, returns: np.ndarray) -> Dict:
        """Тест на ARCH эффект (кластеризация волатильности)."""
        try:
            # Тест на ARCH эффект через автокорреляцию квадратов доходностей
            squared_returns = returns**2
            
            # Рассчитываем автокорреляцию первого порядка для квадратов доходностей
            if len(squared_returns) > 2:
                autocorr_squared = np.corrcoef(squared_returns[:-1], squared_returns[1:])[0, 1]
                
                if np.isfinite(autocorr_squared):
                    # Тест значимости
                    n = len(returns)
                    se = 1 / np.sqrt(n)
                    
                    # Статистика теста
                    t_stat = autocorr_squared / se
                    p_value = 2 * (1 - stats.norm.cdf(abs(t_stat)))
                    
                    has_arch = p_value < self.significance_level and autocorr_squared > 0
                    
                    return {
                        'squared_returns_autocorr': autocorr_squared,
                        'arch_test_statistic': t_stat,
                        'arch_p_value': p_value,
                        'has_arch_effect': has_arch
                    }
            
            return {
                'squared_returns_autocorr': 0,
                'arch_test_statistic': 0,
                'arch_p_value': 1,
                'has_arch_effect': False
            }
            
        except Exception as e:
            self.logger.debug(f"Ошибка в ARCH тесте: {e}")
            return {
                'squared_returns_autocorr': 0,
                'arch_test_statistic': 0,
                'arch_p_value': 1,
                'has_arch_effect': False
            }
    
    def bootstrap_analysis(self, returns: np.ndarray, n_bootstrap: int = 1000) -> Dict:
        """
        Bootstrap анализ для оценки стабильности статистик.
        
        Args:
            returns: Массив доходностей
            n_bootstrap: Количество bootstrap выборок
            
        Returns:
            Dict: Результаты bootstrap анализа
        """
        if len(returns) < 10:
            return {'error': 'Недостаточно данных для bootstrap'}
        
        # Статистики для анализа
        bootstrap_means = []
        bootstrap_stds = []
        bootstrap_sharpe = []
        bootstrap_win_rates = []
        
        original_mean = np.mean(returns)
        original_std = np.std(returns)
        original_sharpe = original_mean / original_std if original_std > 0 else 0
        original_win_rate = np.sum(returns > 0) / len(returns)
        
        # Генерируем bootstrap выборки
        np.random.seed(42)  # Для воспроизводимости
        
        for _ in range(n_bootstrap):
            # Случайная выборка с возвращением
            bootstrap_sample = np.random.choice(returns, size=len(returns), replace=True)
            
            # Рассчитываем статистики
            bs_mean = np.mean(bootstrap_sample)
            bs_std = np.std(bootstrap_sample)
            bs_sharpe = bs_mean / bs_std if bs_std > 0 else 0
            bs_win_rate = np.sum(bootstrap_sample > 0) / len(bootstrap_sample)
            
            bootstrap_means.append(bs_mean)
            bootstrap_stds.append(bs_std)
            bootstrap_sharpe.append(bs_sharpe)
            bootstrap_win_rates.append(bs_win_rate)
        
        # Доверительные интервалы (95%)
        ci_lower = 2.5
        ci_upper = 97.5
        
        results = {
            'original_statistics': {
                'mean': original_mean,
                'std': original_std,
                'sharpe': original_sharpe,
                'win_rate': original_win_rate
            },
            'bootstrap_statistics': {
                'mean': {
                    'mean': np.mean(bootstrap_means),
                    'std': np.std(bootstrap_means),
                    'ci_lower': np.percentile(bootstrap_means, ci_lower),
                    'ci_upper': np.percentile(bootstrap_means, ci_upper)
                },
                'sharpe': {
                    'mean': np.mean(bootstrap_sharpe),
                    'std': np.std(bootstrap_sharpe),
                    'ci_lower': np.percentile(bootstrap_sharpe, ci_lower),
                    'ci_upper': np.percentile(bootstrap_sharpe, ci_upper)
                },
                'win_rate': {
                    'mean': np.mean(bootstrap_win_rates),
                    'std': np.std(bootstrap_win_rates),
                    'ci_lower': np.percentile(bootstrap_win_rates, ci_lower),
                    'ci_upper': np.percentile(bootstrap_win_rates, ci_upper)
                }
            }
        }
        
        # Проверяем стабильность: оригинальная статистика должна быть в доверительном интервале
        mean_stable = (results['bootstrap_statistics']['mean']['ci_lower'] <= 
                      original_mean <= 
                      results['bootstrap_statistics']['mean']['ci_upper'])
        
        sharpe_stable = (results['bootstrap_statistics']['sharpe']['ci_lower'] <= 
                        original_sharpe <= 
                        results['bootstrap_statistics']['sharpe']['ci_upper'])
        
        results['stability'] = {
            'mean_stable': mean_stable,
            'sharpe_stable': sharpe_stable,
            'overall_stable': mean_stable and sharpe_stable
        }
        
        return results
    
    def compare_strategies(self, returns_A: np.ndarray, returns_B: np.ndarray) -> Dict:
        """
        Статистическое сравнение двух стратегий.
        
        Args:
            returns_A: Доходности стратегии A
            returns_B: Доходности стратегии B
            
        Returns:
            Dict: Результаты сравнения
        """
        results = {}

        try:
            # -------------------------------
            # 1. t-тест для сравнения средних
            # -------------------------------
            t_result = ttest_ind(returns_A, returns_B)

            t_stat: float = float(getattr(t_result, "statistic", 0.0))  # type: ignore[attr-defined]
            t_p: float = float(getattr(t_result, "pvalue", 1.0))        # type: ignore[attr-defined]

            if not np.isfinite(t_stat):
                t_stat = 0.0
            if not np.isfinite(t_p):
                t_p = 1.0

            results['t_test'] = {
                'statistic': t_stat,
                'p_value': t_p,
                'A_significantly_better': t_p < self.significance_level and t_stat > 0,
                'B_significantly_better': t_p < self.significance_level and t_stat < 0,
            }

            # -------------------------------
            # 2. Mann-Whitney U test (непараметрический)
            # -------------------------------
            mw_result = stats.mannwhitneyu(list(returns_A), list(returns_B), alternative='two-sided')  # type: ignore
            mw_stat: float = float(getattr(mw_result, 'statistic', 0.0))
            mw_p: float = float(getattr(mw_result, 'pvalue', 1.0))

            results['mann_whitney'] = {
                'statistic': mw_stat,
                'p_value': mw_p,
                'significantly_different': mw_p < self.significance_level
            }

            # -------------------------------
            # 3. Levene test (сравнение дисперсий)
            # -------------------------------
            levene_result = stats.levene(list(returns_A), list(returns_B))  # type: ignore
            levene_stat: float = float(getattr(levene_result, 'statistic', 0.0))
            levene_p: float = float(getattr(levene_result, 'pvalue', 1.0))

            results['levene_test'] = {
                'statistic': levene_stat,
                'p_value': levene_p,
                'equal_variances': levene_p > self.significance_level
            }

            # -------------------------------
            # 4. Описательная статистика
            # -------------------------------
            def descriptive_stats(returns: np.ndarray) -> Dict:
                mean = float(np.mean(returns))
                std = float(np.std(returns))
                sharpe = mean / std if std > 0 else 0.0
                win_rate = float(np.sum(returns > 0) / len(returns))
                return {'mean': mean, 'std': std, 'sharpe': sharpe, 'win_rate': win_rate}

            results['descriptive'] = {
                'A': descriptive_stats(returns_A),
                'B': descriptive_stats(returns_B)
            }

        except Exception as e:
            self.logger.error(f"Ошибка в сравнении стратегий: {e}")
            results['error'] = str(e)
            results['t_test'] = {
                'statistic': 0.0,
                'p_value': 1.0,
                'A_significantly_better': False,
                'B_significantly_better': False
            }
            results['mann_whitney'] = {
                'statistic': 0.0,
                'p_value': 1.0,
                'significantly_different': False
            }
            results['levene_test'] = {
                'statistic': 0.0,
                'p_value': 1.0,
                'equal_variances': True
            }
            results['descriptive'] = {
                'A': {'mean': 0.0, 'std': 0.0, 'sharpe': 0.0, 'win_rate': 0.0},
                'B': {'mean': 0.0, 'std': 0.0, 'sharpe': 0.0, 'win_rate': 0.0}
            }

        return results
