# Диагностика компонентов оптимизатора
# Запусти этот файл для проверки всех зависимостей и импортов

import sys
import traceback
from pathlib import Path

def test_imports():
    """Проверяет все критичные импорты"""
    
    print("🔍 ДИАГНОСТИКА ИМПОРТОВ")
    print("=" * 50)
    
    # Базовые библиотеки
    libraries_to_test = [
        ("pandas", "import pandas as pd"),
        ("numpy", "import numpy as np"),
        ("yfinance", "import yfinance as yf"),
        ("scipy", "import scipy.stats"),
        ("optuna", "import optuna"),
        ("matplotlib", "import matplotlib.pyplot as plt"),
        ("seaborn", "import seaborn as sns"),
        ("sklearn", "from sklearn.metrics import silhouette_score"),
    ]
    
    for name, import_str in libraries_to_test:
        try:
            exec(import_str)
            print(f"✅ {name}")
        except ImportError as e:
            print(f"❌ {name}: {e}")
        except Exception as e:
            print(f"⚠️  {name}: {e}")
    
    print("\n🔍 ДИАГНОСТИКА ВНУТРЕННИХ МОДУЛЕЙ")
    print("=" * 50)
    
    # Добавляем текущую папку в path
    current_dir = Path(__file__).parent
    if str(current_dir) not in sys.path:
        sys.path.insert(0, str(current_dir))
    
    # Внутренние модули
    internal_modules = [
        ("objective_function", "from optimizer.objective_function import OptimizerObjective"),
        ("validation_engine", "from optimizer.validation_engine import ValidationEngine"),
        ("statistical_tests", "from optimizer.statistical_tests import StatisticalValidator"),
        ("utils", "from optimizer.utils import OptimizerUtils"),
        ("bot_process", "from bot_process import Playground"),
        ("metrics_calculator", "from analytics.metrics_calculator import MetricsCalculator"),
        ("config_manager", "from risk_management.config_manager import ConfigManager"),
        ("rsi_sma_strategy", "from strategies.rsi_sma_strategy import Strategy"),
    ]
    
    for name, import_str in internal_modules:
        try:
            exec(import_str)
            print(f"✅ {name}")
        except ImportError as e:
            print(f"❌ {name}: {e}")
        except Exception as e:
            print(f"⚠️  {name}: {e}")

def test_configs():
    """Проверяет конфигурационные файлы"""
    
    print("\n🔍 ДИАГНОСТИКА КОНФИГУРАЦИЙ")
    print("=" * 50)
    
    configs_to_test = [
        ("optimizer_config.json", "optimizer/optimizer_config.json"),
        ("rsi_sma.json", "configs/optimizer/rsi_sma.json"),
        ("live_default.json", "configs/live_default.json"),
    ]
    
    for name, path in configs_to_test:
        try:
            file_path = Path(path)
            if file_path.exists():
                with open(file_path, 'r', encoding='utf-8') as f:
                    import json
                    json.load(f)
                print(f"✅ {name}")
            else:
                print(f"❌ {name}: файл не найден")
        except Exception as e:
            print(f"⚠️  {name}: {e}")

def test_basic_functionality():
    """Тестирует базовую функциональность"""
    
    print("\n🔍 ДИАГНОСТИКА БАЗОВОЙ ФУНКЦИОНАЛЬНОСТИ")
    print("=" * 50)
    
    try:
        # Тест загрузки данных
        print("📊 Тестируем загрузку данных...")
        import yfinance as yf
        df = yf.download("BTC-USD", period="5d", interval="1h", progress=False)
        if df is not None and len(df) > 0:
            print(f"✅ Данные загружены: {len(df)} свечей")
        else:
            print("❌ Не удалось загрузить данные")
            
    except Exception as e:
        print(f"❌ Ошибка загрузки данных: {e}")
    
    try:
        # Тест создания оптимизатора
        print("🚀 Тестируем создание оптимизатора...")
        from optimizer.main_optimizer import AdvancedOptimizer
        optimizer = AdvancedOptimizer()
        print("✅ Оптимизатор создан")
        
    except Exception as e:
        print(f"❌ Ошибка создания оптимизатора: {e}")
        print("Traceback:")
        traceback.print_exc()

def test_strategy_instantiation():
    """Тестирует создание стратегии"""
    
    print("\n🔍 ДИАГНОСТИКА СТРАТЕГИИ")
    print("=" * 50)
    
    try:
        from strategies.rsi_sma_strategy import Strategy
        strategy = Strategy(
            rsi_period=14,
            sma_period=50,
            oversold_level=30,
            tp_multiplier=1.05,
            overbought_level=70
        )
        print(f"✅ Стратегия создана: {strategy.name}")
        
        # Тест анализа
        import pandas as pd
        import numpy as np
        
        # Создаем тестовые данные
        dates = pd.date_range('2023-01-01', periods=100, freq='H')
        test_data = pd.DataFrame({
            'Open': np.random.random(100) * 100 + 50000,
            'High': np.random.random(100) * 100 + 50100,
            'Low': np.random.random(100) * 100 + 49900,
            'Close': np.random.random(100) * 100 + 50000,
            'Volume': np.random.random(100) * 1000
        }, index=dates)
        
        result = strategy.analyze(test_data)
        print(f"✅ Анализ выполнен: {result.get('signal', 'unknown')}")
        
    except Exception as e:
        print(f"❌ Ошибка в стратегии: {e}")
        traceback.print_exc()

def diagnose_full_pipeline():
    """Полная диагностика пайплайна"""
    
    print("\n🔍 ПОЛНАЯ ДИАГНОСТИКА ПАЙПЛАЙНА")
    print("=" * 50)
    
    try:
        # Имитируем запуск оптимизатора
        import json
        from pathlib import Path
        
        # Проверяем аргументы командной строки
        strategy_config_path = "configs/optimizer/rsi_sma.json"
        
        if not Path(strategy_config_path).exists():
            print(f"❌ Конфиг стратегии не найден: {strategy_config_path}")
            return
            
        print(f"✅ Конфиг стратегии найден: {strategy_config_path}")
        
        # Проверяем создание окон walk-forward
        from optimizer.main_optimizer import AdvancedOptimizer
        import pandas as pd
        import numpy as np
        
        # Создаем тестовые данные
        dates = pd.date_range('2023-01-01', periods=2000, freq='H')
        test_data = pd.DataFrame({
            'Open': np.random.random(2000) * 100 + 50000,
            'High': np.random.random(2000) * 100 + 50100,
            'Low': np.random.random(2000) * 100 + 49900,
            'Close': np.random.random(2000) * 100 + 50000,
            'Volume': np.random.random(2000) * 1000
        }, index=dates)
        
        optimizer = AdvancedOptimizer()
        windows = optimizer.create_data_splits(test_data)
        print(f"✅ Создано {len(windows)} окон walk-forward")
        
        # Тест одного окна (без полной оптимизации)
        if windows:
            window = windows[0]
            print(f"✅ Тестовое окно: train={len(window['train_data'])}, "
                  f"val={len(window['val_data'])}, test={len(window['test_data'])}")
        
        print("✅ Базовый пайплайн работает")
        
    except Exception as e:
        print(f"❌ Ошибка в пайплайне: {e}")
        traceback.print_exc()

def main():
    """Основная функция диагностики"""
    
    print("🔧 ДИАГНОСТИКА ТОРГОВОГО ОПТИМИЗАТОРА")
    print("=" * 60)
    print("Проверяем все компоненты системы...\n")
    
    test_imports()
    test_configs() 
    test_basic_functionality()
    test_strategy_instantiation()
    diagnose_full_pipeline()
    
    print("\n" + "=" * 60)
    print("🎯 ДИАГНОСТИКА ЗАВЕРШЕНА")
    print("=" * 60)
    print("\nЕсли все тесты прошли ✅, то проблема в другом месте.")
    print("Если есть ❌, то нужно исправить эти проблемы.")
    print("\nДля получения полного Traceback запусти:")
    print("python optimizer/main_optimizer.py configs/optimizer/rsi_sma.json")

if __name__ == "__main__":
    main()