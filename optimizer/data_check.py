# Проверяем реальные данные и настраиваем walk-forward
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

def check_data_coverage():
    """Проверяем покрытие данных"""
    
    print("📊 ПРОВЕРКА ПОКРЫТИЯ ДАННЫХ")
    print("=" * 50)
    
    # Загружаем те же данные что и в оптимизаторе
    df = yf.download("BTC-USD", period="2y", interval="1h", progress=False)
    
    if df is None or df.empty:
        print("❌ Не удалось загрузить данные")
        return None
        
    print(f"📈 Тикер: BTC-USD")
    print(f"📅 Период: 2y, интервал: 1h") 
    print(f"🔢 Всего свечей: {len(df)}")
    print(f"📆 Начало: {df.index[0]}")
    print(f"📆 Конец: {df.index[-1]}")
    
    # Рассчитываем реальное покрытие
    duration = df.index[-1] - df.index[0]
    days = duration.days
    months = days / 30.44  # Среднее количество дней в месяце
    
    print(f"⏱️  Реальное покрытие: {days} дней ({months:.1f} месяцев)")
    
    return df, months

def suggest_walk_forward_config(available_months):
    """Предлагает оптимальные настройки walk-forward"""
    
    print(f"\n🎯 РЕКОМЕНДАЦИИ ПО WALK-FORWARD")
    print("=" * 50)
    
    # Консервативный подход: используем ~80% данных для создания окон
    usable_months = available_months * 0.8
    
    configs = []
    
    # Вариант 1: Маленькие окна (для быстрого тестирования)
    config1 = {
        "name": "Быстрое тестирование",
        "train_months": 1.0,
        "validation_months": 0.25,  # ~1 неделя
        "test_months": 0.5,         # ~2 недели
        "step_months": 0.25,        # шаг неделя
    }
    window_size1 = config1["train_months"] + config1["validation_months"] + config1["test_months"]
    max_windows1 = int((usable_months - window_size1) / config1["step_months"]) + 1
    
    # Вариант 2: Средние окна (баланс скорость/качество)  
    config2 = {
        "name": "Сбалансированный",
        "train_months": 1.5,
        "validation_months": 0.5,
        "test_months": 0.75,
        "step_months": 0.5,
    }
    window_size2 = config2["train_months"] + config2["validation_months"] + config2["test_months"]
    max_windows2 = int((usable_months - window_size2) / config2["step_months"]) + 1
    
    # Вариант 3: Большие окна (максимальное качество)
    config3 = {
        "name": "Качественный",
        "train_months": 2.0,
        "validation_months": 0.5,
        "test_months": 1.0,
        "step_months": 0.75,
    }
    window_size3 = config3["train_months"] + config3["validation_months"] + config3["test_months"]
    max_windows3 = int((usable_months - window_size3) / config3["step_months"]) + 1
    
    configs = [
        (config1, window_size1, max_windows1),
        (config2, window_size2, max_windows2), 
        (config3, window_size3, max_windows3)
    ]
    
    for i, (config, window_size, max_windows) in enumerate(configs, 1):
        print(f"\n📋 Вариант {i}: {config['name']}")
        print(f"   Размер окна: {window_size:.1f} мес")
        print(f"   Максимум окон: {max_windows}")
        print(f"   Конфиг:")
        for key, value in config.items():
            if key != "name":
                print(f"     \"{key}\": {value},")
        
        if max_windows >= 3:
            print(f"   ✅ Подходит (>= 3 окон)")
        else:
            print(f"   ❌ Не подходит (< 3 окон)")
    
    return configs

def generate_fixed_config(selected_config):
    """Генерирует исправленный конфиг"""
    
    print(f"\n🔧 ИСПРАВЛЕННЫЙ КОНФИГ")
    print("=" * 50)
    
    fixed_config = f'''{{
    "data_settings": {{
        "default_ticker": "BTC-USD",
        "default_period": "2y",
        "default_interval": "1h",
        "min_data_points": 1000
    }},

    "walk_forward": {{
        "train_months": {selected_config["train_months"]},
        "validation_months": {selected_config["validation_months"]},
        "test_months": {selected_config["test_months"]},
        "step_months": {selected_config["step_months"]},
        "min_windows": 3,
        "max_windows": 20
    }},

    "optimization": {{
        "trials_per_window": 15,
        "timeout_minutes": 10,
        "n_jobs": 1,
        "study_direction": "maximize"
    }},

    "validation": {{
        "min_trades_for_significance": 3,
        "statistical_significance_level": 0.05
    }},

    "risk_limits": {{
        "max_drawdown_threshold": 0.20,
        "min_win_rate": 0.20,
        "min_profit_factor": 1.05
    }},

    "metrics_weights": {{
        "sharpe_ratio": 0.4,
        "sortino_ratio": 0.3,
        "calmar_ratio": 0.2,
        "stability_bonus": 0.1
    }},

    "overfitting_detection": {{
        "max_profitable_windows_ratio": 0.90,
        "min_parameter_consistency": 0.2,
        "max_score_degradation": 0.5
    }},

    "reporting": {{
        "charts_directory": "charts/optimizer",
        "export_to_csv": true,
        "chart_dpi": 300,
        "chart_style": "default"
    }},

    "logging": {{
        "level": "INFO",
        "save_to_file": true,
        "log_file": "optimizer.log"
    }}
}}'''

    return fixed_config

def main():
    print("🔍 АНАЛИЗ ДАННЫХ И НАСТРОЙКА WALK-FORWARD")
    print("=" * 60)
    
    # Проверяем данные
    result = check_data_coverage()
    if result is None:
        return
        
    df, available_months = result
    
    # Предлагаем варианты
    configs = suggest_walk_forward_config(available_months)
    
    # Выбираем лучший вариант (первый работающий)
    best_config = None
    for config, window_size, max_windows in configs:
        if max_windows >= 3:
            best_config = config
            break
    
    if best_config:
        print(f"\n🎯 РЕКОМЕНДУЕМЫЙ ВЫБОР: {best_config['name']}")
        
        # Генерируем конфиг
        fixed_config_content = generate_fixed_config(best_config)
        print(fixed_config_content)
        
        print(f"\n💡 ИНСТРУКЦИЯ:")
        print(f"1. Сохрани конфиг выше в файл 'optimizer_config_fixed.json'")
        print(f"2. Запусти: python optimizer/main_optimizer.py configs/optimizer/rsi_sma.json --config optimizer_config_fixed.json")
        print(f"3. Или замени содержимое optimizer/optimizer_config.json")
        
    else:
        print(f"\n❌ НЕДОСТАТОЧНО ДАННЫХ")
        print(f"Доступно {available_months:.1f} месяцев, нужно минимум ~4-5 месяцев")
        print(f"Попробуй другой тикер или больший период")

if __name__ == "__main__":
    main()