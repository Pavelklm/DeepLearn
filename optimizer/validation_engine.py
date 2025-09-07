# Файл: optimizer/validation_engine.py

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
import logging
from scipy import stats
try:
    from sklearn.metrics import silhouette_score
    from sklearn.cluster import KMeans
    SKLEARN_AVAILABLE = True
except ImportError:
    try:
        # Попытка импорта с правильным названием пакета
        import sklearn.metrics
        import sklearn.cluster
        from sklearn.metrics import silhouette_score
        from sklearn.cluster import KMeans
        SKLEARN_AVAILABLE = True
    except ImportError:
        SKLEARN_AVAILABLE = False


class ValidationEngine:
    """
    Движок для валидации результатов оптимизации и детекции overfitting.
    
    Включает:
    1. Детекция переоптимизации по множественным критериям
    2. Анализ стабильности параметров между окнами
    3. Out-of-sample тестирование
    4. Статистическая значимость результатов
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.overfitting_config = config['overfitting_detection']
        self.validation_config = config['validation']
    
    def detect_overfitting(self, train_score: float, val_score: float, test_score: float) -> bool:
        """
        Детектирует overfitting по деградации performance на out-of-sample данных.
        
        Args:
            train_score: Оценка на тренировочных данных
            val_score: Оценка на валидационных данных  
            test_score: Оценка на тестовых данных
            
        Returns:
            bool: True если обнаружен overfitting
        """
        if not all(np.isfinite([train_score, val_score, test_score])):
            return True  # Некорректные scores = подозрение на overfitting
        
        # 1. Деградация от валидации к тесту
        if val_score > 0:
            val_to_test_degradation = (val_score - test_score) / val_score
            if val_to_test_degradation > self.overfitting_config['max_score_degradation']:
                self.logger.debug(f"Детектирована деградация val→test: {val_to_test_degradation:.2%}")
                return True
        
        # 2. Деградация от тренировки к тесту
        if train_score > 0:
            train_to_test_degradation = (train_score - test_score) / train_score
            if train_to_test_degradation > self.overfitting_config['max_score_degradation']:
                self.logger.debug(f"Детектирована деградация train→test: {train_to_test_degradation:.2%}")
                return True
        
        # 3. Тест значительно хуже тренировки (классический признак overfitting)
        if train_score > 0 and test_score < train_score * 0.6:
            self.logger.debug(f"Тест значительно хуже тренировки: {test_score:.3f} vs {train_score:.3f}")
            return True
        
        return False
    
    def analyze_walk_forward_results(self, window_results: List[Dict]) -> Dict:
        """
        Комплексный анализ результатов walk-forward для детекции overfitting.
        
        Args:
            window_results: Результаты всех окон walk-forward
            
        Returns:
            Dict: Детальный анализ с предупреждениями
        """
        successful_windows = [w for w in window_results if w.get('success', False)]
        
        if len(successful_windows) < 2:
            return {
                'status': 'insufficient_data',
                'warnings': ['Недостаточно успешных окон для анализа overfitting'],
                'analysis': {}
            }
        
        analysis = {}
        warnings = []
        
        # 1. Анализ стабильности результатов
        score_analysis = self._analyze_score_stability(successful_windows)
        analysis['score_stability'] = score_analysis
        warnings.extend(score_analysis.get('warnings', []))
        
        # 2. Анализ стабильности параметров
        param_analysis = self._analyze_parameter_stability(successful_windows)
        analysis['parameter_stability'] = param_analysis
        warnings.extend(param_analysis.get('warnings', []))
        
        # 3. Анализ частоты прибыльных окон
        profitability_analysis = self._analyze_profitability_pattern(successful_windows)
        analysis['profitability'] = profitability_analysis
        warnings.extend(profitability_analysis.get('warnings', []))
        
        # 4. Анализ деградации производительности
        degradation_analysis = self._analyze_performance_degradation(successful_windows)
        analysis['degradation'] = degradation_analysis
        warnings.extend(degradation_analysis.get('warnings', []))
        
        # 5. Общий overfitting score
        overfitting_score = self._calculate_overfitting_score(analysis)
        analysis['overfitting_score'] = overfitting_score
        
        # 6. Финальная оценка
        if overfitting_score > 70:
            status = 'high_overfitting_risk'
            warnings.append('🔴 ВЫСОКИЙ РИСК ПЕРЕОПТИМИЗАЦИИ')
        elif overfitting_score > 40:
            status = 'moderate_overfitting_risk'
            warnings.append('🟡 Умеренный риск переоптимизации')
        else:
            status = 'low_overfitting_risk'
        
        return {
            'status': status,
            'overfitting_score': overfitting_score,
            'warnings': warnings,
            'analysis': analysis,
            'successful_windows': len(successful_windows),
            'total_windows': len(window_results)
        }
    
    def _analyze_score_stability(self, windows: List[Dict]) -> Dict:
        """Анализирует стабильность оценок между окнами."""
        test_scores = [w.get('test_score', 0) for w in windows]
        val_scores = [w.get('val_score', 0) for w in windows]
        
        if not test_scores or all(s == 0 for s in test_scores):
            return {'status': 'no_data', 'warnings': ['Нет данных о test scores']}
        
        # Статистика test scores
        test_mean = np.mean(test_scores)
        test_std = np.std(test_scores)
        test_cv = test_std / abs(test_mean) if test_mean != 0 else float('inf')
        
        # Статистика val scores
        val_mean = np.mean(val_scores) if val_scores else 0
        val_std = np.std(val_scores) if val_scores else 0
        
        warnings = []
        
        # Проверяем стабильность
        if test_cv > 1.0:  # Коэффициент вариации > 100%
            warnings.append('⚠️ Крайне нестабильные результаты между окнами')
        elif test_cv > 0.5:
            warnings.append('⚠️ Нестабильные результаты между окнами')
        
        # Проверяем тренд деградации
        correlation_with_time = None
        if len(test_scores) >= 3:
            try:
                # Простой и надежный способ получить корреляцию
                x_values = list(range(len(test_scores)))
                y_values = list(test_scores)
                correlation_result = stats.pearsonr(x_values, y_values)
                
                # Обрабатываем результат универсально
                if isinstance(correlation_result, tuple):
                    corr_value = correlation_result[0]
                else:
                    corr_value = getattr(correlation_result, 'correlation', correlation_result[0])
                
                correlation_with_time = float(corr_value) if not np.isnan(float(corr_value)) else 0.0  # type: ignore
                
                if correlation_with_time < -0.5:
                    warnings.append('📉 Обнаружена деградация performance со временем')
            except Exception as e:
                self.logger.debug(f"Ошибка в расчете корреляции: {e}")
                correlation_with_time = 0.0
        
        return {
            'test_score_mean': test_mean,
            'test_score_std': test_std,
            'test_score_cv': test_cv,
            'val_score_mean': val_mean,
            'score_trend': correlation_with_time if len(test_scores) >= 3 else None,
            'warnings': warnings
        }
    
    def _analyze_parameter_stability(self, windows: List[Dict]) -> Dict:
        """Анализирует стабильность оптимальных параметров."""
        # Собираем все параметры
        all_params = []
        param_names = set()
        
        for window in windows:
            params = window.get('best_params', {})
            if params:
                all_params.append(params)
                param_names.update(params.keys())
        
        if len(all_params) < 2:
            return {'status': 'insufficient_data'}
        
        param_names = list(param_names)
        stability_scores = {}
        warnings = []
        
        for param_name in param_names:
            values = []
            for params in all_params:
                if param_name in params:
                    values.append(params[param_name])
            
            if len(values) < 2:
                continue
            
            # Рассчитываем коэффициент вариации для числовых параметров
            if all(isinstance(v, (int, float)) for v in values):
                mean_val = np.mean(values)
                std_val = np.std(values)
                cv = std_val / abs(mean_val) if mean_val != 0 else float('inf')
                stability_scores[param_name] = {
                    'type': 'numeric',
                    'mean': float(mean_val),
                    'std': float(std_val),
                    'cv': float(cv),
                    'values': values
                }
                
                # Предупреждения по нестабильности
                if cv > self.validation_config['max_parameter_variation_cv']:
                    warnings.append(f'⚠️ Нестабильный параметр {param_name}: CV={cv:.2f}')
            
            else:
                # Для категориальных параметров - частота встречаемости
                from collections import Counter
                value_counts = Counter(values)
                most_common_freq = value_counts.most_common(1)[0][1] / len(values)
                
                stability_scores[param_name] = {
                    'type': 'categorical',
                    'value_counts': dict(value_counts),
                    'consistency': most_common_freq,
                    'values': values
                }
                
                if most_common_freq < self.overfitting_config['min_parameter_consistency']:
                    warnings.append(f'⚠️ Inconsistent categorical parameter {param_name}')
        
        # Общая оценка стабильности параметров
        numeric_cvs = [s['cv'] for s in stability_scores.values() if s['type'] == 'numeric']
        categorical_consistencies = [s['consistency'] for s in stability_scores.values() if s['type'] == 'categorical']
        
        overall_stability = 0.0
        if numeric_cvs:
            avg_cv = float(np.mean(numeric_cvs))
            overall_stability += max(0.0, 1 - avg_cv) * 0.7  # 70% вес числовым параметрам
        
        if categorical_consistencies:
            avg_consistency = np.mean(categorical_consistencies)
            overall_stability += avg_consistency * 0.3  # 30% вес категориальным
        
        return {
            'parameter_stability_scores': stability_scores,
            'overall_stability': overall_stability,
            'warnings': warnings
        }
    
    def _analyze_profitability_pattern(self, windows: List[Dict]) -> Dict:
        """Анализирует паттерны прибыльности окон."""
        profitable_windows = 0
        total_profit = 0.0
        profit_values = []
        
        for window in windows:
            test_metrics = window.get('test_metrics')
            if test_metrics and hasattr(test_metrics, 'total_return_pct'):
                profit_pct = test_metrics.total_return_pct
                profit_values.append(profit_pct)
                total_profit += profit_pct
                if profit_pct > 0:
                    profitable_windows += 1
        
        if not profit_values:
            return {'status': 'no_profit_data'}
        
        profitable_ratio = profitable_windows / len(windows)
        warnings = []
        
        # Слишком много прибыльных окон может указывать на overfitting
        if profitable_ratio > self.overfitting_config['max_profitable_windows_ratio']:
            warnings.append(f'🚨 Подозрительно много прибыльных окон: {profitable_ratio:.1%}')
        
        # Анализ распределения прибыли
        profit_std = np.std(profit_values)
        profit_mean = np.mean(profit_values)
        
        return {
            'profitable_windows': profitable_windows,
            'total_windows': len(windows),
            'profitable_ratio': profitable_ratio,
            'avg_profit_pct': profit_mean,
            'profit_volatility': profit_std,
            'total_profit_pct': total_profit,
            'warnings': warnings
        }
    
    def _analyze_performance_degradation(self, windows: List[Dict]) -> Dict:
        """Анализирует деградацию производительности train→val→test."""
        degradations = []
        warnings = []
        
        for window in windows:
            train_score = window.get('train_score', 0)
            val_score = window.get('val_score', 0)
            test_score = window.get('test_score', 0)
            
            if all(score > 0 for score in [train_score, val_score, test_score]):
                train_to_val = (train_score - val_score) / train_score
                val_to_test = (val_score - test_score) / val_score
                train_to_test = (train_score - test_score) / train_score
                
                degradations.append({
                    'window_id': window.get('window_id'),
                    'train_to_val': train_to_val,
                    'val_to_test': val_to_test,
                    'train_to_test': train_to_test
                })
        
        if not degradations:
            return {'status': 'no_data'}
        
        # Средние деградации
        avg_train_to_val = np.mean([d['train_to_val'] for d in degradations])
        avg_val_to_test = np.mean([d['val_to_test'] for d in degradations])
        avg_train_to_test = np.mean([d['train_to_test'] for d in degradations])
        
        # Предупреждения
        if avg_train_to_test > 0.3:
            warnings.append('🔴 Сильная деградация от тренировки к тесту')
        elif avg_train_to_test > 0.15:
            warnings.append('🟡 Умеренная деградация от тренировки к тесту')
        
        return {
            'avg_train_to_val_degradation': avg_train_to_val,
            'avg_val_to_test_degradation': avg_val_to_test,
            'avg_train_to_test_degradation': avg_train_to_test,
            'individual_degradations': degradations,
            'warnings': warnings
        }
    
    def _calculate_overfitting_score(self, analysis: Dict) -> float:
        """
        Рассчитывает общий score риска overfitting (0-100, где 100 = максимальный риск).
        """
        score = 0.0
        
        # 1. Стабильность результатов (30% веса)
        score_stability = analysis.get('score_stability', {})
        test_cv = score_stability.get('test_score_cv', 0)
        score += min(30, test_cv * 50)  # CV > 0.6 даёт максимальные 30 баллов
        
        # 2. Стабильность параметров (25% веса)
        param_stability = analysis.get('parameter_stability', {})
        overall_stability = param_stability.get('overall_stability', 1.0)
        score += (1 - overall_stability) * 25
        
        # 3. Подозрительная прибыльность (25% веса)
        profitability = analysis.get('profitability', {})
        profitable_ratio = profitability.get('profitable_ratio', 0.5)
        if profitable_ratio > 0.8:
            score += (profitable_ratio - 0.8) * 125  # Максимум 25 баллов
        
        # 4. Деградация производительности (20% веса)
        degradation = analysis.get('degradation', {})
        avg_degradation = degradation.get('avg_train_to_test_degradation', 0)
        score += min(20, avg_degradation * 50)  # Деградация > 0.4 даёт максимальные 20 баллов
        
        return min(100, score)
    
    def validate_robustness(self, best_params: Dict, strategy_config_path: str, 
                           data: pd.DataFrame, objective_func) -> Dict:
        """
        Тест робастности: проверяет стабильность стратегии при небольших изменениях параметров.
        
        Args:
            best_params: Лучшие найденные параметры
            strategy_config_path: Путь к конфигу стратегии
            data: Данные для тестирования
            objective_func: Функция оценки стратегии
            
        Returns:
            Dict: Результаты теста робастности
        """
        noise_level = self.validation_config['parameter_noise_level']
        n_variations = self.validation_config['robustness_test_variations']
        
        # Генерируем вариации параметров
        parameter_variations = self._generate_parameter_variations(
            best_params, noise_level, n_variations
        )
        
        # Тестируем каждую вариацию
        scores = []
        for variation in parameter_variations:
            try:
                result = objective_func.evaluate_fixed_params(
                    variation, data, strategy_config_path, mode='robustness'
                )
                scores.append(result['score'])
            except Exception as e:
                self.logger.debug(f"Ошибка в robustness test: {e}")
                scores.append(0.0)  # Штрафная оценка
        
        # Анализируем результаты
        original_score = objective_func.evaluate_fixed_params(
            best_params, data, strategy_config_path, mode='robustness'
        )['score']
        
        scores_array = np.array(scores)
        mean_score = np.mean(scores_array)
        std_score = np.std(scores_array)
        
        # Коэффициент стабильности
        stability_coefficient = 1 - (std_score / abs(mean_score)) if mean_score != 0 else 0
        
        # Процент вариаций лучше оригинала
        better_variations = np.sum(scores_array > original_score) / len(scores_array)
        
        return {
            'original_score': original_score,
            'variation_scores': scores,
            'mean_variation_score': mean_score,
            'std_variation_score': std_score,
            'stability_coefficient': stability_coefficient,
            'better_variations_pct': better_variations,
            'robust': stability_coefficient > 0.7 and better_variations < 0.3
        }
    
    def _generate_parameter_variations(self, base_params: Dict, noise_level: float, 
                                     n_variations: int) -> List[Dict]:
        """Генерирует вариации параметров с добавлением шума."""
        variations = []
        
        for _ in range(n_variations):
            variation = {}
            for param_name, base_value in base_params.items():
                if isinstance(base_value, (int, float)):
                    # Добавляем гауссовский шум
                    noise = np.random.normal(0, abs(base_value) * noise_level)
                    new_value = base_value + noise
                    
                    # Сохраняем тип параметра
                    if isinstance(base_value, int):
                        variation[param_name] = int(round(new_value))
                    else:
                        variation[param_name] = new_value
                else:
                    # Для категориальных параметров оставляем без изменений
                    variation[param_name] = base_value
            
            variations.append(variation)
        
        return variations