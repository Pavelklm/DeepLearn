# Файл: optimizer/__init__.py

"""Продвинутая система оптимизации торговых стратегий с защитой от overfitting.

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

# Основные импорты
try:
    from .main_optimizer import AdvancedOptimizer
    from .objective_function import OptimizerObjective  
    from .validation_engine import ValidationEngine
    from .statistical_tests import StatisticalValidator
    from .utils import OptimizerUtils, OptimizerReporter
except ImportError:
    # Fallback для случая прямого запуска
    import sys
    import os
    from pathlib import Path
    
    # Добавляем текущую директорию в sys.path
    current_dir = Path(__file__).parent.absolute()
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))
    
    try:
        from main_optimizer import AdvancedOptimizer
        from objective_function import OptimizerObjective  
        from validation_engine import ValidationEngine
        from statistical_tests import StatisticalValidator
        from utils import OptimizerUtils, OptimizerReporter
    except ImportError as e:
        print(f"⚠️ Не удалось импортировать модули оптимизатора: {e}")
        print(f"Убедитесь, что все файлы находятся в директории: {current_dir}")
        # Не поднимаем ошибку, чтобы модуль мог загрузиться частично
        AdvancedOptimizer = None
        OptimizerObjective = None
        ValidationEngine = None
        StatisticalValidator = None
        OptimizerUtils = None
        OptimizerReporter = None

__all__ = [
    'AdvancedOptimizer',
    'OptimizerObjective', 
    'ValidationEngine',
    'StatisticalValidator',
    'OptimizerUtils',
    'OptimizerReporter'
]