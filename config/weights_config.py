# =============================================================================
# ФОРМУЛЫ РАСЧЕТА ВЕСОВ ОРДЕРОВ
# =============================================================================

import math

# ВРЕМЕННЫЕ ФАКТОРЫ
# =============================================================================
TIME_FACTORS_CONFIG = {
    "methods": {
        # Линейные методы
        "linear_1h": lambda t: min(t / 60, 1.0),
        "linear_4h": lambda t: min(t / 240, 1.0), 
        "linear_8h": lambda t: min(t / 480, 1.0),
        
        # Экспоненциальные методы  
        "exponential_30m": lambda t: 1 - math.exp(-t / 30),
        "exponential_60m": lambda t: 1 - math.exp(-t / 60),
        "exponential_2h": lambda t: 1 - math.exp(-t / 120),
        
        # Логарифмические методы
        "logarithmic_2h": lambda t: math.log(1 + t) / math.log(121),
        "logarithmic_4h": lambda t: math.log(1 + t) / math.log(241),
        
        # Корневые методы
        "sqrt_4h": lambda t: math.sqrt(t) / math.sqrt(240),
        "sqrt_8h": lambda t: math.sqrt(t) / math.sqrt(480),
        
        # Адаптивные методы (зависят от волатильности)
        "adaptive_volatility": lambda t, vol: (1 - math.exp(-t / (30 * (1 + vol)))) * (1 - vol/2),
        "adaptive_market": lambda t, market_temp: 1 - math.exp(-t / (30 * market_temp))
    },
    
    # Веса важности каждого метода в финальном расчете
    "weights": {
        "linear_1h": 0.1,
        "exponential_30m": 0.2, 
        "exponential_60m": 0.15,
        "logarithmic_2h": 0.1,
        "sqrt_4h": 0.1,
        "adaptive_volatility": 0.25,
        "adaptive_market": 0.1
    }
}

# АЛГОРИТМЫ ФИНАЛЬНОГО ВЕСА
# =============================================================================  
WEIGHT_ALGORITHMS = {
    "conservative": {
        "time_weight": 0.4,
        "size_weight": 0.25, 
        "round_level_weight": 0.15,
        "volatility_weight": 0.1,
        "growth_weight": 0.1,
        "description": "Консервативный алгоритм, упор на время жизни"
    },
    
    "aggressive": {
        "time_weight": 0.2,
        "size_weight": 0.3,
        "round_level_weight": 0.2, 
        "volatility_weight": 0.15,
        "growth_weight": 0.15,
        "description": "Агрессивный алгоритм, быстро реагирует на изменения"
    },
    
    "volume_weighted": {
        "time_weight": 0.25,
        "size_weight": 0.4,
        "round_level_weight": 0.1,
        "volatility_weight": 0.15, 
        "growth_weight": 0.1,
        "description": "Упор на размер ордеров"
    },
    
    "time_weighted": {
        "time_weight": 0.5,
        "size_weight": 0.2,
        "round_level_weight": 0.1,
        "volatility_weight": 0.1,
        "growth_weight": 0.1,
        "description": "Максимальный упор на время жизни"
    },
    
    "hybrid": {
        "time_weight": 0.3,
        "size_weight": 0.25,
        "round_level_weight": 0.2,
        "volatility_weight": 0.15,
        "growth_weight": 0.1, 
        "description": "Сбалансированный подход"
    }
}

# РЕКОМЕНДУЕМЫЙ АЛГОРИТМ (используется по умолчанию)
RECOMMENDED_ALGORITHM = "hybrid"

# РЫНОЧНЫЕ МОДИФИКАТОРЫ
# =============================================================================
MARKET_MODIFIERS = {
    # Модификаторы времени суток (UTC)
    "time_of_day": {
        "asian_session": (0, 8, 1.2),    # Повышенная активность
        "london_session": (8, 16, 1.0),   # Нормальная активность
        "new_york_session": (16, 24, 1.1), # Слегка повышенная
    },
    
    # Модификаторы дня недели
    "day_of_week": {
        "monday": 1.1,     # Начало недели
        "tuesday": 1.0,    # Обычный день
        "wednesday": 1.0,  # Обычный день  
        "thursday": 1.0,   # Обычный день
        "friday": 0.9,     # Конец недели
        "saturday": 0.7,   # Выходной
        "sunday": 0.8      # Выходной
    },
    
    # Модификаторы волатильности рынка
    "market_volatility": {
        "very_low": (0, 0.01, 1.3),      # Спокойный рынок - ордера ценнее
        "low": (0.01, 0.02, 1.1),        # Низкая волатильность  
        "normal": (0.02, 0.05, 1.0),     # Нормальная волатильность
        "high": (0.05, 0.1, 0.8),        # Высокая волатильность
        "extreme": (0.1, float('inf'), 0.6)  # Экстремальная волатильность
    }
}

# НАСТРОЙКИ РАСЧЕТОВ
# =============================================================================
CALCULATION_CONFIG = {
    # Максимальные значения для нормализации
    "max_volatility": 0.2,        # 20% - максимальная волатильность
    "max_growth_factor": 3.0,     # Максимальный рост ордера в 3 раза
    "max_size_multiplier": 10.0,  # Максимум в 10 раз больше средней
    
    # Минимальные пороги
    "min_usd_value": 1000,        # Минимальная стоимость ордера $1000
    "min_lifetime_seconds": 30,   # Минимальное время жизни 30 сек
    
    # Сглаживание
    "smoothing_factor": 0.1,      # Фактор сглаживания резких изменений
    "outlier_threshold": 3.0      # Порог для определения выбросов (сигма)
}
