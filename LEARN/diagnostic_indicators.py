# diagnostic_indicators.py
# Диагностика проблем с индикаторами в эволюционном оптимизаторе

import pandas as pd
import yfinance as yf
import talib
import numpy as np
import random

def test_indicator_generation():
    """Тестируем, что происходит с индикаторами."""
    
    print("🔍 ДИАГНОСТИКА ИНДИКАТОРОВ")
    print("="*50)
    
    # Загружаем тестовые данные
    print("📈 Загружаем данные...")
    data = yf.download("BTC-USD", period="3mo", interval="1d", progress=False)
    
    # Исправляем проблему с мультииндексными колонками
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.droplevel(1)
    
    print(f"✅ Загружено {len(data)} свечей")
    print(f"🏛️ Исходные колонки: {list(data.columns)}")
    
    # Подготавливаем данные (как в вашем коде)
    clean_data = data.dropna().copy()
    enriched_data = data.copy()
    
    print(f"📊 Данные после очистки: {len(clean_data)} строк")
    
    # Подготавливаем массивы для TA-Lib
    close = clean_data['Close'].astype(float).values
    high = clean_data['High'].astype(float).values
    low = clean_data['Low'].astype(float).values
    volume = clean_data['Volume'].astype(float).values
    
    print(f"📈 Массивы подготовлены: close={len(close)}, high={len(high)}, low={len(low)}")
    
    # Тестовые индикаторы с параметрами
    test_indicators = {
        'RSI': {'timeperiod': 14},
        'SMA': {'timeperiod': 20},
        'EMA': {'timeperiod': 15},
        'MACD': {'fastperiod': 12, 'slowperiod': 26, 'signalperiod': 9},
        'STOCH': {'fastk_period': 14, 'slowk_period': 3, 'slowd_period': 3},
        'CCI': {'timeperiod': 14},
        'MFI': {'timeperiod': 14},
        'WILLR': {'timeperiod': 14}
    }
    
    print(f"\n🎯 Тестируем индикаторы: {list(test_indicators.keys())}")
    
    # Добавляем каждый индикатор (ТОЧНО КАК В ВАШЕМ КОДЕ)
    for indicator_name, params in test_indicators.items():
        try:
            print(f"\n  🔧 Добавляем {indicator_name} с параметрами {params}")
            
            if hasattr(talib, indicator_name.upper()):
                indicator_func = getattr(talib, indicator_name.upper())
                
                if indicator_name.upper() == 'RSI':
                    result = indicator_func(close, timeperiod=params.get('timeperiod', 14))
                    enriched_data['RSI'] = pd.Series(result, index=clean_data.index)
                    print(f"    ✅ Добавлен RSI -> колонка 'RSI'")
                
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
                    print(f"    ✅ Добавлен MACD -> колонки 'MACD', 'MACD_signal', 'MACD_hist'")
                
                elif indicator_name.upper() == 'SMA':
                    result = indicator_func(close, timeperiod=params.get('timeperiod', 20))
                    enriched_data['SMA'] = pd.Series(result, index=clean_data.index)
                    print(f"    ✅ Добавлен SMA -> колонка 'SMA'")
                
                elif indicator_name.upper() == 'EMA':
                    result = indicator_func(close, timeperiod=params.get('timeperiod', 20))
                    enriched_data['EMA'] = pd.Series(result, index=clean_data.index)
                    print(f"    ✅ Добавлен EMA -> колонка 'EMA'")
                
                elif indicator_name.upper() == 'STOCH':
                    slowk, slowd = indicator_func(
                        high, low, close,
                        fastk_period=params.get('fastk_period', 14),
                        slowk_period=params.get('slowk_period', 3),
                        slowd_period=params.get('slowd_period', 3)
                    )
                    enriched_data['STOCH_k'] = pd.Series(slowk, index=clean_data.index)
                    enriched_data['STOCH_d'] = pd.Series(slowd, index=clean_data.index)
                    print(f"    ✅ Добавлен STOCH -> колонки 'STOCH_k', 'STOCH_d'")
                
                elif indicator_name.upper() == 'CCI':
                    result = indicator_func(high, low, close, timeperiod=params.get('timeperiod', 14))
                    enriched_data['CCI'] = pd.Series(result, index=clean_data.index)
                    print(f"    ✅ Добавлен CCI -> колонка 'CCI'")
                
                elif indicator_name.upper() == 'MFI':
                    if volume is not None:
                        result = indicator_func(high, low, close, volume, timeperiod=params.get('timeperiod', 14))
                        enriched_data['MFI'] = pd.Series(result, index=clean_data.index)
                        print(f"    ✅ Добавлен MFI -> колонка 'MFI'")
                
                elif indicator_name.upper() == 'WILLR':
                    result = indicator_func(high, low, close, timeperiod=params.get('timeperiod', 14))
                    enriched_data['WILLR'] = pd.Series(result, index=clean_data.index)
                    print(f"    ✅ Добавлен WILLR -> колонка 'WILLR'")
                
            else:
                print(f"    ❌ Индикатор {indicator_name} не найден в TA-Lib")
                
        except Exception as e:
            print(f"    ❌ Ошибка с {indicator_name}: {e}")
    
    # Результат
    print(f"\n📋 ИТОГОВЫЕ КОЛОНКИ:")
    original_cols = list(data.columns)
    new_cols = [col for col in enriched_data.columns if col not in original_cols]
    
    print(f"  📊 Исходных: {original_cols}")
    print(f"  🆕 Добавленных: {new_cols}")
    
    # Проверяем наличие данных
    print(f"\n🔍 ПРОВЕРКА ДАННЫХ:")
    for col in new_cols:
        non_na_count = enriched_data[col].notna().sum()
        print(f"  {col}: {non_na_count}/{len(enriched_data)} не-NaN значений")
        
        # Показываем последние 3 значения
        last_values = enriched_data[col].dropna().tail(3).values
        print(f"    Последние значения: {last_values}")
    
    return enriched_data, new_cols

def test_condition_generation_vs_reality(available_indicators):
    """Тестируем совпадение генерируемых условий с реальными колонками."""
    
    print(f"\n\n🎲 ПРОВЕРКА СОВПАДЕНИЯ УСЛОВИЙ И КОЛОНОК")
    print("="*50)
    
    # Симулируем то, что делает _generate_conditions
    indicator_pool = ['RSI', 'SMA', 'EMA', 'MACD', 'STOCH', 'CCI', 'MFI', 'WILLR']
    
    print(f"🎯 Индикаторы в пуле (из indicator_pool): {indicator_pool}")
    print(f"🔧 Реально созданные колонки: {available_indicators}")
    
    # Проверяем совпадения
    print(f"\n🔍 ПРОВЕРКА СОВПАДЕНИЙ:")
    for indicator in indicator_pool:
        if indicator in available_indicators:
            print(f"  ✅ {indicator}: СОВПАДАЕТ")
        else:
            # Ищем похожие
            similar = [col for col in available_indicators if indicator in col]
            if similar:
                print(f"  ⚠️ {indicator}: НЕ СОВПАДАЕТ, но есть похожие: {similar}")
            else:
                print(f"  ❌ {indicator}: НЕ НАЙДЕН")
    
    return indicator_pool

def test_condition_evaluation(enriched_data, new_cols):
    """Тестируем оценку условий на реальных данных."""
    
    print(f"\n\n🧮 ТЕСТИРОВАНИЕ ОЦЕНКИ УСЛОВИЙ")
    print("="*50)
    
    if len(enriched_data) < 10:
        print("❌ Недостаточно данных для тестирования")
        return
    
    # Берем последнюю строку для тестирования
    test_row = enriched_data.iloc[-1]
    print(f"📊 Тестовая строка: {test_row.name}")
    
    # Создаем тестовые условия для каждого доступного индикатора
    print(f"\n🎯 Генерируем тестовые условия для {len(new_cols)} индикаторов:")
    
    successful_conditions = 0
    failed_conditions = 0
    
    for i, col in enumerate(new_cols):
        print(f"\n  Условие #{i+1}: Тестируем '{col}'")
        
        # Проверяем наличие в данных
        if col not in test_row:
            print(f"    ❌ Колонка '{col}' НЕ НАЙДЕНА в test_row")
            failed_conditions += 1
            continue
        
        value = test_row[col]
        print(f"    📈 Значение: {value}")
        
        # Проверяем на NaN
        if pd.isna(value):
            print(f"    ❌ Значение NaN")
            failed_conditions += 1
            continue
        
        # Создаем условие, которое должно пройти
        threshold = float(value) * 0.9  # На 10% меньше текущего значения
        condition = {
            'type': 'threshold',
            'indicator': col,
            'operator': '>',
            'threshold': threshold
        }
        
        print(f"    🎯 Условие: {value} > {threshold}")
        
        # Оцениваем условие (как в вашем коде)
        try:
            if condition['operator'] == '>':
                result = float(value) > float(threshold)
            else:
                result = False
            
            print(f"    ✅ Результат: {result}")
            if result:
                successful_conditions += 1
            else:
                failed_conditions += 1
                
        except Exception as e:
            print(f"    ❌ Ошибка оценки: {e}")
            failed_conditions += 1
    
    print(f"\n📊 ИТОГИ ТЕСТИРОВАНИЯ УСЛОВИЙ:")
    print(f"  ✅ Успешных: {successful_conditions}")
    print(f"  ❌ Провалов: {failed_conditions}")
    # Избегаем деление на ноль
    total_conditions = successful_conditions + failed_conditions
    if total_conditions > 0:
        print(f"  📈 Успешность: {successful_conditions/total_conditions*100:.1f}%")
    else:
        print(f"  📈 Успешность: 0.0% (нет условий для тестирования)")

def main():
    """Главная функция диагностики."""
    
    try:
        print("🚀 ЗАПУСК ДИАГНОСТИКИ ЭВОЛЮЦИОННОГО ОПТИМИЗАТОРА")
        print("="*60)
        
        # 1. Тестируем добавление индикаторов
        enriched_data, new_cols = test_indicator_generation()
        
        # 2. Проверяем совпадение имен
        indicator_pool = test_condition_generation_vs_reality(new_cols)
        
        # 3. Тестируем оценку условий
        test_condition_evaluation(enriched_data, new_cols)
        
        # 4. Итоговые выводы
        print(f"\n\n🎯 ИТОГОВЫЕ ВЫВОДЫ:")
        print("="*50)
        
        if len(new_cols) == 0:
            print("❌ КРИТИЧНО: Ни один индикатор не был добавлен!")
            print("   Проверьте работу TA-Lib и логику _add_indicators")
        else:
            print(f"✅ Добавлено {len(new_cols)} индикаторов")
        
        # Проверяем конфликты именования
        conflicts = []
        for indicator in indicator_pool:
            if indicator not in new_cols:
                similar = [col for col in new_cols if indicator in col]
                if similar:
                    conflicts.append((indicator, similar))
        
        if conflicts:
            print(f"\n⚠️ НАЙДЕНЫ КОНФЛИКТЫ ИМЕНОВАНИЯ:")
            for base_name, actual_names in conflicts:
                print(f"   '{base_name}' -> {actual_names}")
            print("   ☝️ Эти конфликты могут приводить к 'indicator not found' ошибкам!")
        
        print(f"\n🏁 ДИАГНОСТИКА ЗАВЕРШЕНА")
        
    except Exception as e:
        print(f"❌ Критическая ошибка диагностики: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
    