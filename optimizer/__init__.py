# Файл: optimizer/__init__.py

"""
Продвинутая система оптимизации торговых стратегий с защитой от overfitting.

Модули:
- main_optimizer: Главный класс AdvancedOptimizer 
- objective_function: Улучшенная objective function с научными принципами
- validation_engine: Детекция переоптимизации и валидация
- statistical_tests: Статистические тесты и анализ
- utils: Утилиты и генератор отчетов

Основные принципы:
1. Трехчастное разделение данных (train/validation/test)
2. Walk-forward анализ с адаптивными параметрами  
3. Статистическая валидация результатов
4. Детекция переоптимизации по множественным критериям
5. Робастность-тесты для проверки стабильности

Пример использования:
    from optimizer import AdvancedOptimizer
    
    optimizer = AdvancedOptimizer('path/to/optimizer_config.json')
    results = optimizer.run_strategy_optimization('path/to/strategy_config.json')
"""

__version__ = "1.0.0"
__author__ = "Trading Optimizer Team"

from .main_optimizer import AdvancedOptimizer
from .objective_function import OptimizerObjective  
from .validation_engine import ValidationEngine
from .statistical_tests import StatisticalValidator
from .utils import OptimizerUtils, OptimizerReporter

__all__ = [
    'AdvancedOptimizer',
    'OptimizerObjective', 
    'ValidationEngine',
    'StatisticalValidator',
    'OptimizerUtils',
    'OptimizerReporter'
]