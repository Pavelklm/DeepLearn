# Файл: optimizer/utils.py

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
import json
import time
import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')


class OptimizerUtils:
    """
    Утилиты для анализа результатов оптимизации.
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
    
    def find_robust_parameters(self, window_results: List[Dict]) -> Optional[Dict]:
        """
        Находит наиболее робастные параметры на основе консистентности между окнами.
        
        Args:
            window_results: Результаты всех окон walk-forward
            
        Returns:
            Dict: Лучшие робастные параметры или None
        """
        successful_windows = [w for w in window_results if w.get('success', False)]
        
        if len(successful_windows) < 2:
            self.logger.warning("Недостаточно успешных окон для поиска робастных параметров")
            return None
        
        # Собираем все параметры и их оценки
        param_scores = {}
        
        for window in successful_windows:
            params = window.get('best_params', {})
            score = window.get('test_score', 0)
            
            for param_name, param_value in params.items():
                if param_name not in param_scores:
                    param_scores[param_name] = []
                param_scores[param_name].append((param_value, score))
        
        # Для каждого параметра находим значение с лучшим средним скором
        robust_params = {}
        
        for param_name, value_score_pairs in param_scores.items():
            if not value_score_pairs:
                continue
            
            # Группируем по значениям и считаем средние скоры
            value_groups = {}
            for value, score in value_score_pairs:
                # Для числовых параметров группируем близкие значения
                if isinstance(value, (int, float)):
                    # Округляем для группировки
                    if isinstance(value, int):
                        group_key = value
                    else:
                        group_key = round(value, 2)
                else:
                    group_key = value
                
                if group_key not in value_groups:
                    value_groups[group_key] = []
                value_groups[group_key].append(score)
            
            # Находим значение с лучшим средним скором
            best_value = None
            best_avg_score = -float('inf')
            
            for group_value, scores in value_groups.items():
                avg_score = np.mean(scores)
                if avg_score > best_avg_score:
                    best_avg_score = avg_score
                    best_value = group_value
            
            robust_params[param_name] = best_value
        
        self.logger.info(f"Найдены робастные параметры: {robust_params}")
        return robust_params
    
    def calculate_parameter_stability(self, window_results: List[Dict]) -> Dict:
        """
        Рассчитывает стабильность параметров между окнами.
        
        Args:
            window_results: Результаты окон
            
        Returns:
            Dict: Метрики стабильности параметров
        """
        successful_windows = [w for w in window_results if w.get('success', False)]
        
        if len(successful_windows) < 2:
            return {'status': 'insufficient_data'}
        
        # Собираем параметры
        all_params = []
        param_names = set()
        
        for window in successful_windows:
            params = window.get('best_params', {})
            if params:
                all_params.append(params)
                param_names.update(params.keys())
        
        if not all_params:
            return {'status': 'no_parameters'}
        
        stability_metrics = {}
        
        for param_name in param_names:
            values = []
            for params in all_params:
                if param_name in params:
                    values.append(params[param_name])
            
            if len(values) < 2:
                continue
            
            if all(isinstance(v, (int, float)) for v in values):
                # Численный параметр
                mean_val = np.mean(values)
                std_val = np.std(values)
                cv = std_val / abs(mean_val) if mean_val != 0 else float('inf')
                
                stability_metrics[param_name] = {
                    'type': 'numeric',
                    'values': values,
                    'mean': float(mean_val),
                    'std': float(std_val),
                    'coefficient_of_variation': float(cv),
                    'min': float(min(values)),
                    'max': float(max(values)),
                    'range_pct': float((max(values) - min(values)) / mean_val * 100) if mean_val != 0 else 0.0
                }
            else:
                # Категориальный параметр
                from collections import Counter
                value_counts = Counter(values)
                most_common = value_counts.most_common(1)[0]
                consistency = most_common[1] / len(values)
                
                stability_metrics[param_name] = {
                    'type': 'categorical',
                    'values': values,
                    'value_counts': dict(value_counts),
                    'most_common_value': most_common[0],
                    'consistency': consistency,
                    'unique_values': len(value_counts)
                }
        
        # Общая оценка стабильности
        numeric_cvs = [m['coefficient_of_variation'] for m in stability_metrics.values() 
                      if m['type'] == 'numeric']
        categorical_consistencies = [m['consistency'] for m in stability_metrics.values() 
                                   if m['type'] == 'categorical']
        
        overall_stability = 0.0
        if numeric_cvs:
            avg_cv = np.mean(numeric_cvs)
            numeric_stability = max(0, 1 - avg_cv / 2)  # CV = 2 дает стабильность 0
            overall_stability += numeric_stability * 0.7
        
        if categorical_consistencies:
            avg_consistency = np.mean(categorical_consistencies)
            overall_stability += avg_consistency * 0.3
        
        return {
            'status': 'success',
            'parameter_metrics': stability_metrics,
            'overall_stability': overall_stability,
            'summary': {
                'total_parameters': len(stability_metrics),
                'numeric_parameters': len(numeric_cvs),
                'categorical_parameters': len(categorical_consistencies),
                'avg_numeric_cv': np.mean(numeric_cvs) if numeric_cvs else None,
                'avg_categorical_consistency': np.mean(categorical_consistencies) if categorical_consistencies else None
            }
        }


class OptimizerReporter:
    """
    Генератор отчетов и визуализаций для оптимизатора.
    """
    
    def __init__(self, config: Dict):
        self.config = config
        self.logger = logging.getLogger(__name__)
        self.charts_dir = Path(config['reporting']['charts_directory'])
        self.charts_dir.mkdir(parents=True, exist_ok=True)
        
        # Настройка стилей графиков
        try:
            plt.style.use(config['reporting']['chart_style'])
        except:
            plt.style.use('default')
        
        sns.set_palette("husl")
    
    def generate_full_report(self, results: Dict, data: pd.DataFrame):
        """
        Генерирует полный отчет по результатам оптимизации.
        
        Args:
            results: Результаты оптимизации
            data: Исходные данные
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        strategy_name = Path(results['strategy_config']).stem
        
        self.logger.info("🎨 Генерируем отчеты и визуализации...")
        
        try:
            # 1. Основные графики walk-forward
            self._generate_walk_forward_charts(results, strategy_name, timestamp)
            
            # 2. Анализ параметров
            self._generate_parameter_analysis_charts(results, strategy_name, timestamp)
            
            # 3. Детальная статистика
            self._generate_detailed_statistics_chart(results, strategy_name, timestamp)
            
            # 4. Сравнительный анализ
            if results.get('final_backtest'):
                self._generate_final_backtest_chart(results, data, strategy_name, timestamp)
            
            # 5. CSV отчеты
            if self.config['reporting']['export_to_csv']:
                self._export_csv_reports(results, strategy_name, timestamp)
            
            # 6. JSON отчет
            self._save_json_report(results, strategy_name, timestamp)
            
            self.logger.info(f"✅ Отчеты сохранены в {self.charts_dir}")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка генерации отчетов: {e}")
    
    def _generate_walk_forward_charts(self, results: Dict, strategy_name: str, timestamp: str):
        """Генерирует основные графики walk-forward анализа."""
        window_results = results['window_results']
        successful_windows = [w for w in window_results if w.get('success', False)]
        
        if not successful_windows:
            self.logger.warning("Нет успешных окон для графиков")
            return
        
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle(f'Walk-Forward Analysis: {strategy_name}', fontsize=16, fontweight='bold')
        
        window_ids = [w['window_id'] for w in successful_windows]
        test_scores = [w.get('test_score', 0) for w in successful_windows]
        val_scores = [w.get('val_score', 0) for w in successful_windows]
        train_scores = [w.get('train_score', 0) for w in successful_windows]
        trade_counts = [w.get('test_trades', 0) for w in successful_windows]
        
        # 1. Сравнение Train/Val/Test scores
        ax1.plot(window_ids, train_scores, 'o-', label='Train Score', linewidth=2, markersize=6)
        ax1.plot(window_ids, val_scores, 's-', label='Validation Score', linewidth=2, markersize=6)
        ax1.plot(window_ids, test_scores, '^-', label='Test Score', linewidth=2, markersize=6)
        ax1.set_title('🎯 Оценки по окнам', fontweight='bold')
        ax1.set_xlabel('Номер окна')
        ax1.set_ylabel('Оценка')
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # 2. Прибыльность по окнам
        profits = []
        for w in successful_windows:
            metrics = w.get('test_metrics')
            if metrics and hasattr(metrics, 'total_return_pct'):
                profits.append(metrics.total_return_pct)
            else:
                profits.append(0)
        
        colors = ['green' if p > 0 else 'red' for p in profits]
        bars = ax2.bar(window_ids, profits, color=colors, alpha=0.7, edgecolor='black')
        ax2.axhline(0, color='black', alpha=0.3)
        ax2.set_title('💰 Прибыльность по окнам (%)', fontweight='bold')
        ax2.set_xlabel('Номер окна')
        ax2.set_ylabel('Прибыль (%)')
        ax2.grid(True, alpha=0.3)
        
        # Подписи значений на барах
        for bar, profit in zip(bars, profits):
            height = bar.get_height()
            ax2.text(bar.get_x() + bar.get_width()/2., height + (0.1 if height > 0 else -0.3),
                    f'{profit:.1f}%', ha='center', va='bottom' if height > 0 else 'top', fontsize=9)
        
        # 3. Количество сделок
        ax3.bar(window_ids, trade_counts, color='orange', alpha=0.7, edgecolor='black')
        ax3.set_title('📊 Количество сделок по окнам', fontweight='bold')
        ax3.set_xlabel('Номер окна')
        ax3.set_ylabel('Количество сделок')
        ax3.grid(True, alpha=0.3)
        
        # 4. Деградация производительности
        degradations = []
        for w in successful_windows:
            train_score = w.get('train_score', 0)
            test_score = w.get('test_score', 0)
            if train_score > 0:
                degradation = (train_score - test_score) / train_score * 100
                degradations.append(degradation)
            else:
                degradations.append(0)
        
        ax4.plot(window_ids, degradations, 'ro-', linewidth=2, markersize=6)
        ax4.axhline(0, color='green', alpha=0.5, linestyle='--', label='Нет деградации')
        ax4.axhline(30, color='red', alpha=0.5, linestyle='--', label='Критическая деградация')
        ax4.set_title('📉 Деградация Train→Test (%)', fontweight='bold')
        ax4.set_xlabel('Номер окна')
        ax4.set_ylabel('Деградация (%)')
        ax4.legend()
        ax4.grid(True, alpha=0.3)
        
        plt.tight_layout()
        filename = self.charts_dir / f"WalkForward_{strategy_name}_{timestamp}.png"
        plt.savefig(filename, dpi=self.config['reporting']['chart_dpi'], 
                   bbox_inches='tight', facecolor='white')
        plt.close()
        
        self.logger.info(f"📊 График walk-forward сохранен: {filename}")
    
    def _generate_parameter_analysis_charts(self, results: Dict, strategy_name: str, timestamp: str):
        """Генерирует графики анализа параметров."""
        window_results = results['window_results']
        successful_windows = [w for w in window_results if w.get('success', False)]
        
        if len(successful_windows) < 2:
            return
        
        # Собираем параметры
        all_params = {}
        param_names = set()
        
        for w in successful_windows:
            params = w.get('best_params', {})
            window_id = w['window_id']
            
            for param_name, param_value in params.items():
                if param_name not in all_params:
                    all_params[param_name] = {'windows': [], 'values': []}
                
                all_params[param_name]['windows'].append(window_id)
                all_params[param_name]['values'].append(param_value)
                param_names.add(param_name)
        
        if not param_names:
            return
        
        # Создаем графики
        n_params = len(param_names)
        n_cols = min(3, n_params)
        n_rows = (n_params + n_cols - 1) // n_cols
        
        fig, axes = plt.subplots(n_rows, n_cols, figsize=(5*n_cols, 4*n_rows))
        fig.suptitle(f'Анализ стабильности параметров: {strategy_name}', fontsize=16, fontweight='bold')
        
        if n_params == 1:
            axes = [axes]
        elif n_rows == 1:
            axes = [axes] if n_cols == 1 else axes
        else:
            axes = axes.flatten()
        
        for idx, param_name in enumerate(param_names):
            ax = axes[idx] if idx < len(axes) else None
            if ax is None:
                break
            
            windows = all_params[param_name]['windows']
            values = all_params[param_name]['values']
            
            if all(isinstance(v, (int, float)) for v in values):
                # Числовой параметр - линейный график
                ax.plot(windows, values, 'o-', linewidth=2, markersize=8)
                ax.set_ylabel('Значение параметра')
                
                # Добавляем статистику
                mean_val = np.mean(values)
                std_val = np.std(values)
                ax.axhline(mean_val, color='red', alpha=0.5, linestyle='--', 
                          label=f'Среднее: {mean_val:.2f}')
                ax.fill_between(windows, mean_val - std_val, mean_val + std_val, 
                               alpha=0.2, color='red', label=f'±1σ: {std_val:.2f}')
                ax.legend()
            else:
                # Категориальный параметр - подсчет частот
                from collections import Counter
                value_counts = Counter(values)
                
                categories = list(value_counts.keys())
                counts = list(value_counts.values())
                
                ax.bar(categories, counts, alpha=0.7)
                ax.set_ylabel('Частота')
                
                # Поворачиваем подписи если много категорий
                if len(categories) > 3:
                    ax.tick_params(axis='x', rotation=45)
            
            ax.set_title(f'{param_name}', fontweight='bold')
            ax.set_xlabel('Номер окна')
            ax.grid(True, alpha=0.3)
        
        # Убираем лишние subplot'ы
        for idx in range(n_params, len(axes)):
            fig.delaxes(axes[idx])
        
        plt.tight_layout()
        filename = self.charts_dir / f"Parameters_{strategy_name}_{timestamp}.png"
        plt.savefig(filename, dpi=self.config['reporting']['chart_dpi'], 
                   bbox_inches='tight', facecolor='white')
        plt.close()
        
        self.logger.info(f"📊 График параметров сохранен: {filename}")
    
    def _generate_detailed_statistics_chart(self, results: Dict, strategy_name: str, timestamp: str):
        """Генерирует детальную статистику."""
        analysis = results.get('analysis', {})
        
        if not analysis:
            return
        
        fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
        fig.suptitle(f'Детальный анализ: {strategy_name}', fontsize=16, fontweight='bold')
        
        # 1. Overfitting Score
        overfitting_score = analysis.get('overfitting_score', 0)
        colors = ['green' if overfitting_score < 40 else 'orange' if overfitting_score < 70 else 'red']
        
        ax1.bar(['Overfitting Score'], [overfitting_score], color=colors, alpha=0.7)
        ax1.axhline(40, color='orange', alpha=0.5, linestyle='--', label='Умеренный риск')
        ax1.axhline(70, color='red', alpha=0.5, linestyle='--', label='Высокий риск')
        ax1.set_title('🎯 Риск переоптимизации', fontweight='bold')
        ax1.set_ylabel('Score (0-100)')
        ax1.set_ylim(0, 100)
        ax1.legend()
        ax1.grid(True, alpha=0.3)
        
        # Добавляем текст с оценкой
        if overfitting_score < 40:
            verdict = "✅ Низкий риск"
        elif overfitting_score < 70:
            verdict = "⚠️ Умеренный риск"
        else:
            verdict = "🚨 Высокий риск"
        
        ax1.text(0, overfitting_score + 5, f'{overfitting_score:.1f}\n{verdict}', 
                ha='center', va='bottom', fontweight='bold', fontsize=12)
        
        # 2. Статистика успешности
        total_windows = results['total_windows']
        successful_windows = results['successful_windows']
        
        success_data = [successful_windows, total_windows - successful_windows]
        success_labels = ['Успешные', 'Неуспешные']
        colors_pie = ['green', 'red']
        
        ax2.pie(success_data, labels=success_labels, colors=colors_pie, autopct='%1.1f%%', startangle=90)
        ax2.set_title(f'📊 Успешность окон\n({successful_windows}/{total_windows})', fontweight='bold')
        
        # 3. Распределение оценок
        window_results = results['window_results']
        successful_test_scores = [w.get('test_score', 0) for w in window_results if w.get('success', False)]
        
        if successful_test_scores:
            ax3.hist(successful_test_scores, bins=min(10, len(successful_test_scores)), 
                    alpha=0.7, color='blue', edgecolor='black')
            ax3.axvline(np.mean(successful_test_scores), color='red', linestyle='--', 
                       label=f'Среднее: {np.mean(successful_test_scores):.3f}')
            ax3.set_title('📈 Распределение Test Scores', fontweight='bold')
            ax3.set_xlabel('Test Score')
            ax3.set_ylabel('Частота')
            ax3.legend()
            ax3.grid(True, alpha=0.3)
        else:
            ax3.text(0.5, 0.5, 'Нет успешных окон', ha='center', va='center', transform=ax3.transAxes)
            ax3.set_title('📈 Распределение Test Scores', fontweight='bold')
        
        # 4. Временная стабильность
        if len(successful_test_scores) >= 3:
            window_ids = [w['window_id'] for w in window_results if w.get('success', False)]
            correlation = np.corrcoef(window_ids, successful_test_scores)[0, 1]
            
            ax4.scatter(window_ids, successful_test_scores, alpha=0.7, s=100)
            
            # Линия тренда
            z = np.polyfit(window_ids, successful_test_scores, 1)
            p = np.poly1d(z)
            ax4.plot(window_ids, p(window_ids), "r--", alpha=0.8, 
                    label=f'Тренд (r={correlation:.3f})')
            
            ax4.set_title('⏰ Стабильность во времени', fontweight='bold')
            ax4.set_xlabel('Номер окна')
            ax4.set_ylabel('Test Score')
            ax4.legend()
            ax4.grid(True, alpha=0.3)
            
            # Интерпретация корреляции
            if correlation < -0.5:
                trend_text = "📉 Деградация"
            elif correlation > 0.3:
                trend_text = "📈 Улучшение"
            else:
                trend_text = "➡️ Стабильно"
            
            ax4.text(0.05, 0.95, trend_text, transform=ax4.transAxes, 
                    fontweight='bold', fontsize=12, va='top')
        else:
            ax4.text(0.5, 0.5, 'Недостаточно данных\nдля анализа тренда', 
                    ha='center', va='center', transform=ax4.transAxes)
            ax4.set_title('⏰ Стабильность во времени', fontweight='bold')
        
        plt.tight_layout()
        filename = self.charts_dir / f"Statistics_{strategy_name}_{timestamp}.png"
        plt.savefig(filename, dpi=self.config['reporting']['chart_dpi'], 
                   bbox_inches='tight', facecolor='white')
        plt.close()
        
        self.logger.info(f"📊 График статистики сохранен: {filename}")
    
    def _generate_final_backtest_chart(self, results: Dict, data: pd.DataFrame, 
                                     strategy_name: str, timestamp: str):
        """Генерирует график финального бэктеста."""
        final_backtest = results.get('final_backtest')
        if not final_backtest or not final_backtest.get('success'):
            return
        
        # Здесь можно добавить логику для построения equity curve
        # Пока создаем простой информационный график
        
        fig, ax = plt.subplots(1, 1, figsize=(12, 8))
        
        metrics = final_backtest.get('metrics')
        if metrics:
            # Создаем информационную панель
            info_text = f"""
            ФИНАЛЬНЫЙ БЭКТЕСТ: {strategy_name}
            
            📈 Общая доходность: {metrics.total_return_pct:.2f}%
            📊 Sharpe Ratio: {metrics.sharpe_ratio:.3f}
            📊 Sortino Ratio: {metrics.sortino_ratio:.3f}
            📊 Calmar Ratio: {metrics.calmar_ratio:.3f}
            📉 Max Drawdown: {metrics.max_drawdown_pct:.2f}%
            
            📅 Период: {data.index[0].date()} - {data.index[-1].date()}
            🔢 Всего данных: {len(data)} свечей
            
            Лучшие параметры:
            {json.dumps(results.get('best_parameters', {}), indent=2)}
            """
            
            ax.text(0.05, 0.95, info_text, transform=ax.transAxes, fontsize=12,
                   verticalalignment='top', fontfamily='monospace',
                   bbox=dict(boxstyle="round,pad=0.5", facecolor="lightblue", alpha=0.7))
        
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.axis('off')
        ax.set_title(f'Итоговые результаты: {strategy_name}', fontsize=16, fontweight='bold')
        
        plt.tight_layout()
        filename = self.charts_dir / f"FinalBacktest_{strategy_name}_{timestamp}.png"
        plt.savefig(filename, dpi=self.config['reporting']['chart_dpi'], 
                   bbox_inches='tight', facecolor='white')
        plt.close()
        
        self.logger.info(f"📊 График финального бэктеста сохранен: {filename}")
    
    def _export_csv_reports(self, results: Dict, strategy_name: str, timestamp: str):
        """Экспортирует результаты в CSV файлы."""
        try:
            # 1. Сводка по окнам
            window_results = results['window_results']
            df_windows = pd.DataFrame(window_results)
            
            csv_windows = self.charts_dir / f"Windows_{strategy_name}_{timestamp}.csv"
            df_windows.to_csv(csv_windows, index=False)
            
            # 2. Лучшие параметры (если есть)
            if results.get('best_parameters'):
                df_params = pd.DataFrame([results['best_parameters']])
                csv_params = self.charts_dir / f"BestParams_{strategy_name}_{timestamp}.csv"
                df_params.to_csv(csv_params, index=False)
            
            self.logger.info(f"💾 CSV отчеты сохранены в {self.charts_dir}")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка экспорта CSV: {e}")
    
    def _save_json_report(self, results: Dict, strategy_name: str, timestamp: str):
        """Сохраняет полный отчет в JSON."""
        try:
            # Создаем копию результатов для сериализации
            json_results = self._prepare_for_json(results)
            
            json_file = self.charts_dir / f"Report_{strategy_name}_{timestamp}.json"
            with open(json_file, 'w', encoding='utf-8') as f:
                json.dump(json_results, f, indent=2, ensure_ascii=False, default=str)
            
            self.logger.info(f"💾 JSON отчет сохранен: {json_file}")
            
        except Exception as e:
            self.logger.error(f"❌ Ошибка сохранения JSON: {e}")
    
    def _prepare_for_json(self, obj):
        """Подготавливает объект для JSON сериализации."""
        if hasattr(obj, '__dict__'):
            return self._prepare_for_json(obj.__dict__)
        elif isinstance(obj, dict):
            return {key: self._prepare_for_json(value) for key, value in obj.items()}
        elif isinstance(obj, list):
            return [self._prepare_for_json(item) for item in obj]
        elif isinstance(obj, (np.integer, np.floating)):
            return float(obj)
        elif isinstance(obj, np.ndarray):
            return obj.tolist()
        elif pd.isna(obj):
            return None
        else:
            return obj
    
    def print_summary(self, results: Dict):
        """Выводит краткую сводку результатов."""
        print("\n" + "="*80)
        print("🎉 СВОДКА РЕЗУЛЬТАТОВ ОПТИМИЗАЦИИ")
        print("="*80)
        
        strategy_name = Path(results['strategy_config']).stem
        print(f"📋 Стратегия: {strategy_name}")
        print(f"⏱️  Время выполнения: {results['execution_time_minutes']:.1f} минут")
        print(f"🗓️  Дата: {results['timestamp']}")
        
        print("\n📊 СТАТИСТИКА ОКОН:")
        print(f"   ✅ Успешных окон: {results['successful_windows']}/{results['total_windows']} "
              f"({results['successful_windows']/results['total_windows']*100:.1f}%)")
        
        analysis = results.get('analysis', {})
        if analysis:
            overfitting_score = analysis.get('overfitting_score', 0)
            print(f"   🎯 Overfitting Score: {overfitting_score:.1f}/100")
            
            if overfitting_score < 40:
                verdict = "🟢 Низкий риск переоптимизации"
            elif overfitting_score < 70:
                verdict = "🟡 Умеренный риск переоптимизации"
            else:
                verdict = "🔴 Высокий риск переоптимизации"
            print(f"   📋 Оценка: {verdict}")
        
        # Лучшие параметры
        best_params = results.get('best_parameters')
        if best_params:
            print(f"\n🏆 ЛУЧШИЕ ПАРАМЕТРЫ:")
            for param, value in best_params.items():
                print(f"   {param}: {value}")
        
        # Финальный бэктест
        final_backtest = results.get('final_backtest')
        if final_backtest and final_backtest.get('success'):
            metrics = final_backtest.get('metrics')
            if metrics:
                print(f"\n💰 ФИНАЛЬНЫЙ БЭКТЕСТ:")
                print(f"   📈 Общая доходность: {metrics.total_return_pct:.2f}%")
                print(f"   📊 Sharpe Ratio: {metrics.sharpe_ratio:.3f}")
                print(f"   📊 Sortino Ratio: {metrics.sortino_ratio:.3f}")
                print(f"   📉 Max Drawdown: {metrics.max_drawdown_pct:.2f}%")
        
        # Предупреждения
        warnings = results.get('overfitting_warnings', [])
        if warnings:
            print(f"\n⚠️ ПРЕДУПРЕЖДЕНИЯ:")
            for warning in warnings:
                print(f"   • {warning}")
        
        print("\n" + "="*80)