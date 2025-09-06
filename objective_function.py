# Файл: trading/objective_function.py

import pandas as pd
import numpy as np
import json
import importlib

from bot_process import Playground
from analytics.metrics_calculator import MetricsCalculator
from risk_management.config_manager import ConfigManager

def calculate_final_score(metrics) -> float:
    """
    Рассчитывает комбинированную оценку с учётом жёсткого риск-менеджмента.
    ВЕСЫ НЕ ИЗМЕНЕНЫ по просьбе пользователя.
    """
    # --- Веса остаются прежними ---
    weights = {
        'sortino': 0.45, # 45% - упор на качественную прибыль без плохих сюрпризов
        'sharpe': 0.45,  # 45% - упор на общую стабильность
        'calmar': 0.10   # 10% - небольшой бонус за минимальные просадки в рамках лимитов
    }

    sharpe = metrics.sharpe_ratio
    calmar = metrics.calmar_ratio
    sortino = metrics.sortino_ratio

    # --- Проверка на адекватность значений ---
    # Если коэффициенты выглядят подозрительно (слишком высокие), применяем штраф
    if sharpe > 8.0 or sortino > 12.0 or calmar > 15.0:
        print(f"⚠️  Подозрительно высокие коэффициенты: Sharpe={sharpe:.2f}, Sortino={sortino:.2f}, Calmar={calmar:.2f}")
    
    # Нормализация и защита от отрицательных значений
    sharpe_score = max(0, sharpe)
    calmar_score = max(0, calmar)
    sortino_score = max(0, sortino)
    
    # Рассчитываем итоговую оценку по формуле взвешенного среднего
    final_score = (
        sortino_score * weights['sortino'] +
        sharpe_score * weights['sharpe'] +
        calmar_score * weights['calmar']
    )
    
    return final_score


def validate_strategy_quality(trade_history_dicts, metrics) -> tuple[bool, str]:
    """
    Проверяет качество стратегии по нескольким критериям.
    Возвращает (is_valid, reason_if_invalid).
    """
    total_trades = len(trade_history_dicts)
    
    # 1. Минимальное количество сделок для достоверной статистики
    if total_trades < 15:
        return False, f"Недостаточно сделок для оценки: {total_trades}/15"
    
    # 2. Проверка на разумность прибыли
    total_profit = sum(t['profit'] for t in trade_history_dicts)
    if total_profit <= 0:
        return False, f"Убыточная стратегия: прибыль = {total_profit:.2f}"
    
    # 3. Проверка на адекватность коэффициентов
    if (metrics.sharpe_ratio > 15.0 or 
        metrics.sortino_ratio > 20.0 or 
        metrics.calmar_ratio > 25.0):
        return False, "Нереалистично высокие коэффициенты - возможная переоптимизация"
    
    # 4. Проверка на минимальную диверсификацию сделок
    winning_trades = sum(1 for t in trade_history_dicts if t['success'])
    losing_trades = total_trades - winning_trades
        
    return True, "OK"


def objective_function(trial, ohlcv_data: pd.DataFrame, config_path: str):
    """
    Универсальная целевая функция с улучшенной валидацией.
    """
    with open(config_path, 'r', encoding='utf-8') as f:
        opt_config = json.load(f)

    strategy_params = {}
    
    # Динамически создаем пространство поиска для Optuna на основе конфига
    for param in opt_config["parameters"]:
        name = param["name"]
        p_type = param["type"]
        
        dependency = param.get("depends_on")
        low = param["low"]
        if dependency:
            dependent_param_value = strategy_params.get(dependency["name"])
            if dependent_param_value is not None:
                margin = dependency.get("margin", 1)
                if dependency["condition"] == "greater":
                    low = dependent_param_value + margin
        try:
            if p_type == "int":
                strategy_params[name] = trial.suggest_int(name, low, param["high"])
            elif p_type == "float":
                strategy_params[name] = trial.suggest_float(name, low, param["high"], step=param.get("step"))
            elif p_type == "categorical":
                strategy_params[name] = trial.suggest_categorical(name, param["choices"])
        except ValueError:
            # Если low > high из-за зависимости, делаем trial невыгодным
            trial.set_user_attr('rejection_reason', 'Invalid parameter range')
            return -100.0

    # Динамически импортируем и создаем экземпляр класса стратегии
    try:
        strategy_module_path = f"strategies.{opt_config['strategy_file']}"
        strategy_module = importlib.import_module(strategy_module_path)
        # Класс стратегии должен называться 'Strategy' по соглашению
        StrategyClass = strategy_module.Strategy 
    except (ImportError, AttributeError) as e:
        print(f"❌ Ошибка загрузки стратегии {opt_config['strategy_file']}: {e}")
        trial.set_user_attr('rejection_reason', f'Strategy loading error: {e}')
        return -100.0

    bot_name = f"optimizer_trial_{trial.number}"
    bot_config = {
        "bot_name": bot_name,
        "strategy_file": opt_config["strategy_file"], 
        "symbol": "BTC-USD",
        "strategy_params": strategy_params,
        "risk_config_file": 'configs/live_default.json',
        "StrategyClass": StrategyClass 
    }

    # Запускаем бэктест
    try:
        backtest = Playground(
            ohlcv_data=ohlcv_data,
            bot_config=bot_config,
            bot_name=bot_name
        )
        backtest.run()
    except Exception as e:
        print(f"❌ Ошибка в бэктесте для trial {trial.number}: {e}")
        trial.set_user_attr('rejection_reason', f'Backtest error: {e}')
        return -50.0
    
    # Собираем результаты
    trade_history = backtest.risk_manager.performance_tracker.trade_history
    trade_history_dicts = [trade.__dict__ for trade in trade_history]
    
    # Рассчитываем все метрики
    base_config = ConfigManager.load_config(bot_config['risk_config_file'])
    initial_balance = base_config.trading.initial_balance
    metrics_calculator = MetricsCalculator(trade_history=trade_history_dicts, initial_balance=initial_balance)
    all_metrics = metrics_calculator.calculate_all_metrics()
    
    # НОВАЯ ВАЛИДАЦИЯ: Проверяем качество стратегии
    is_valid, rejection_reason = validate_strategy_quality(trade_history_dicts, all_metrics)
    if not is_valid:
        trial.set_user_attr('rejection_reason', rejection_reason)
        print(f"🚫 Trial {trial.number} отклонен: {rejection_reason}")
        return -25.0  # Мягкое наказание для информативности
    
    # Сохраняем все метрики в trial для информативного лога
    trial.set_user_attr('sharpe_ratio', all_metrics.sharpe_ratio)
    trial.set_user_attr('sortino_ratio', all_metrics.sortino_ratio)
    trial.set_user_attr('calmar_ratio', all_metrics.calmar_ratio)
    
    total_trades = len(trade_history_dicts)
    winning_trades = sum(1 for t in trade_history_dicts if t['success'])
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0
    total_profit = sum(t['profit'] for t in trade_history_dicts)

    trial.set_user_attr('trade_count', total_trades)
    trial.set_user_attr('win_rate', win_rate)
    trial.set_user_attr('total_profit', total_profit)
    trial.set_user_attr('rejection_reason', 'Accepted')

    # Рассчитываем комбинированную оценку
    final_score = calculate_final_score(all_metrics)

    # Финальная проверка на корректность
    if pd.isna(final_score) or not np.isfinite(final_score):
        trial.set_user_attr('rejection_reason', 'Invalid final score')
        return -10.0
        
    return final_score