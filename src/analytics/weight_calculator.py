"""
Модуль для расчета весов ордеров
"""

import math
from datetime import datetime, timezone
from typing import Dict, List, Optional

from config.weights_config import (
    TIME_FACTORS_CONFIG, 
    WEIGHT_ALGORITHMS, 
    MARKET_MODIFIERS, 
    CALCULATION_CONFIG,
    RECOMMENDED_ALGORITHM
)
from config.main_config import PSYCHOLOGICAL_LEVELS
from src.utils.logger import get_component_logger

logger = get_component_logger("weight_calculator")


class WeightCalculator:
    """
    Калькулятор весов для ордеров в горячем пуле
    """
    
    def __init__(self):
        self.logger = logger
        
    def calculate_order_weight(self, order_data: dict, market_context: dict = None) -> dict:
        """
        Рассчитать все веса для ордера
        
        Args:
            order_data: Данные ордера
            market_context: Контекст рынка (волатильность, время и тд)
            
        Returns:
            Словарь с различными весами и категориями
        """
        if not order_data:
            return {}
        
        # Базовые параметры
        lifetime_seconds = self._calculate_lifetime_seconds(order_data)
        usd_value = order_data.get("usd_value", 0)
        size_vs_average = order_data.get("size_vs_average", 1.0)
        
        # Рассчитываем временные факторы
        time_factors = self._calculate_time_factors(lifetime_seconds, market_context)
        
        # Рассчитываем контекстные факторы
        context_factors = self._calculate_context_factors(order_data, market_context)
        
        # Рассчитываем финальные веса по разным алгоритмам
        weights = {}
        categories = {}
        
        for algorithm_name, algorithm_config in WEIGHT_ALGORITHMS.items():
            weight = self._calculate_algorithm_weight(
                order_data, time_factors, context_factors, algorithm_config
            )
            weights[algorithm_name] = weight
            categories[f"by_{algorithm_name}"] = self._categorize_weight(weight)
        
        # Рекомендуемый вес
        weights["recommended"] = weights.get(RECOMMENDED_ALGORITHM, 0.0)
        categories["recommended"] = categories.get(f"by_{RECOMMENDED_ALGORITHM}", "basic")
        
        return {
            "time_factors": time_factors,
            "context_factors": context_factors,
            "weights": weights,
            "categories": categories,
            "calculation_timestamp": datetime.now(timezone.utc).isoformat()
        }
    
    def _calculate_lifetime_seconds(self, order_data: dict) -> float:
        """Рассчитать время жизни ордера в секундах"""
        first_seen_str = order_data.get("first_seen")
        if not first_seen_str:
            return 0.0
        
        try:
            first_seen = datetime.fromisoformat(first_seen_str.replace('Z', '+00:00'))
            lifetime = datetime.now(timezone.utc) - first_seen
            return lifetime.total_seconds()
        except Exception:
            return 0.0
    
    def _calculate_time_factors(self, lifetime_seconds: float, market_context: dict = None) -> dict:
        """
        Рассчитать все временные факторы
        
        Args:
            lifetime_seconds: Время жизни в секундах
            market_context: Контекст рынка
            
        Returns:
            Словарь временных факторов
        """
        if lifetime_seconds < CALCULATION_CONFIG["min_lifetime_seconds"]:
            return {method: 0.0 for method in TIME_FACTORS_CONFIG["methods"]}
        
        lifetime_minutes = lifetime_seconds / 60.0
        factors = {}
        
        for method_name, method_func in TIME_FACTORS_CONFIG["methods"].items():
            try:
                if method_name in ["adaptive_volatility", "adaptive_market"]:
                    # Методы требующие дополнительных параметров
                    if market_context:
                        if method_name == "adaptive_volatility":
                            volatility = market_context.get("symbol_volatility_1h", 0.05)
                            factors[method_name] = method_func(lifetime_minutes, volatility)
                        elif method_name == "adaptive_market":
                            market_temp = market_context.get("market_temperature", 1.0)
                            factors[method_name] = method_func(lifetime_minutes, market_temp)
                    else:
                        factors[method_name] = 0.0
                else:
                    # Простые методы только с временем
                    factors[method_name] = method_func(lifetime_minutes)
                
                # Ограничиваем значения
                factors[method_name] = max(0.0, min(1.0, factors[method_name]))
                
            except Exception as e:
                self.logger.warning("Error calculating time factor", 
                                   method=method_name, error=str(e))
                factors[method_name] = 0.0
        
        return factors
    
    def _calculate_context_factors(self, order_data: dict, market_context: dict = None) -> dict:
        """
        Рассчитать контекстные факторы (размер, уровни, волатильность)
        
        Args:
            order_data: Данные ордера
            market_context: Контекст рынка
            
        Returns:
            Словарь контекстных факторов
        """
        factors = {}
        
        # Фактор размера (нормализованный размер относительно среднего)
        size_vs_average = order_data.get("size_vs_average", 1.0)
        factors["size_factor"] = min(1.0, size_vs_average / CALCULATION_CONFIG["max_size_multiplier"])
        
        # Фактор психологического уровня
        factors["round_level_factor"] = self._calculate_round_level_factor(order_data)
        
        # Фактор волатильности
        if market_context:
            symbol_volatility = market_context.get("symbol_volatility_1h", 0.05)
            factors["volatility_factor"] = min(1.0, symbol_volatility / CALCULATION_CONFIG["max_volatility"])
        else:
            factors["volatility_factor"] = 0.5  # Среднее значение
        
        # Фактор роста ордера
        factors["growth_factor"] = self._calculate_growth_factor(order_data)
        
        # Рыночные модификаторы
        factors["time_modifier"] = self._calculate_time_modifier()
        factors["day_modifier"] = self._calculate_day_modifier()
        factors["market_volatility_modifier"] = self._calculate_market_volatility_modifier(market_context)
        
        return factors
    
    def _calculate_round_level_factor(self, order_data: dict) -> float:
        """
        Рассчитать фактор близости к психологическому уровню
        
        Args:
            order_data: Данные ордера
            
        Returns:
            Фактор от 0.0 до 1.0
        """
        order_price = order_data.get("price", 0)
        if not order_price:
            return 0.0
        
        # Ищем ближайший круглый уровень
        round_numbers = PSYCHOLOGICAL_LEVELS["round_numbers"]
        threshold = PSYCHOLOGICAL_LEVELS["proximity_threshold"]
        
        min_distance = float('inf')
        
        for base in round_numbers:
            # Проверяем разные степени этого числа
            for multiplier in [0.1, 1, 10, 100, 1000]:
                level = base * multiplier
                if level <= 0:
                    continue
                
                distance = abs(order_price - level) / level
                min_distance = min(min_distance, distance)
        
        # Если расстояние меньше порога - высокий фактор
        if min_distance <= threshold:
            return 1.0 - (min_distance / threshold)
        
        return 0.0
    
    def _calculate_growth_factor(self, order_data: dict) -> float:
        """
        Рассчитать фактор роста ордера
        
        Args:
            order_data: Данные ордера
            
        Returns:
            Фактор от 0.0 до 1.0
        """
        # Пока простая реализация на основе scan_count
        scan_count = order_data.get("scan_count", 1)
        
        # Чем больше сканов - тем стабильнее ордер
        growth_factor = min(1.0, scan_count / 50.0)  # Нормализуем к 50 сканам
        
        return growth_factor
    
    def _calculate_time_modifier(self) -> float:
        """
        Модификатор времени суток
        
        Returns:
            Модификатор от 0.5 до 1.5
        """
        current_hour = datetime.now(timezone.utc).hour
        
        for session_name, (start, end, modifier) in MARKET_MODIFIERS["time_of_day"].items():
            if start <= current_hour < end:
                return modifier
        
        return 1.0  # По умолчанию
    
    def _calculate_day_modifier(self) -> float:
        """
        Модификатор дня недели
        
        Returns:
            Модификатор от 0.5 до 1.5
        """
        current_day = datetime.now(timezone.utc).strftime('%A').lower()
        return MARKET_MODIFIERS["day_of_week"].get(current_day, 1.0)
    
    def _calculate_market_volatility_modifier(self, market_context: dict = None) -> float:
        """
        Модификатор рыночной волатильности
        
        Args:
            market_context: Контекст рынка
            
        Returns:
            Модификатор от 0.5 до 1.5
        """
        if not market_context:
            return 1.0
        
        market_vol = market_context.get("market_volatility", 0.05)
        
        for vol_range, (min_vol, max_vol, modifier) in MARKET_MODIFIERS["market_volatility"].items():
            if min_vol <= market_vol < max_vol:
                return modifier
        
        return 1.0
    
    def _calculate_algorithm_weight(self, order_data: dict, time_factors: dict, 
                                   context_factors: dict, algorithm_config: dict) -> float:
        """
        Рассчитать итоговый вес по конкретному алгоритму
        
        Args:
            order_data: Данные ордера
            time_factors: Временные факторы
            context_factors: Контекстные факторы
            algorithm_config: Конфигурация алгоритма
            
        Returns:
            Итоговый вес от 0.0 до 1.0
        """
        # Базовые компоненты веса
        time_component = self._calculate_weighted_time_factor(time_factors)
        size_component = context_factors.get("size_factor", 0.0)
        round_level_component = context_factors.get("round_level_factor", 0.0)
        volatility_component = 1.0 - context_factors.get("volatility_factor", 0.5)  # Инвертируем
        growth_component = context_factors.get("growth_factor", 0.0)
        
        # Применяем веса алгоритма
        weighted_sum = (
            time_component * algorithm_config["time_weight"] +
            size_component * algorithm_config["size_weight"] +
            round_level_component * algorithm_config["round_level_weight"] +
            volatility_component * algorithm_config["volatility_weight"] +
            growth_component * algorithm_config["growth_weight"]
        )
        
        # Применяем рыночные модификаторы
        market_modifier = (
            context_factors.get("time_modifier", 1.0) *
            context_factors.get("day_modifier", 1.0) *
            context_factors.get("market_volatility_modifier", 1.0)
        ) / 3.0  # Нормализуем
        
        final_weight = weighted_sum * market_modifier
        
        # Ограничиваем в диапазоне [0, 1]
        return max(0.0, min(1.0, final_weight))
    
    def _calculate_weighted_time_factor(self, time_factors: dict) -> float:
        """
        Рассчитать взвешенный временной фактор
        
        Args:
            time_factors: Словарь временных факторов
            
        Returns:
            Взвешенный временной фактор
        """
        weighted_sum = 0.0
        total_weight = 0.0
        
        for method_name, weight in TIME_FACTORS_CONFIG["weights"].items():
            factor_value = time_factors.get(method_name, 0.0)
            weighted_sum += factor_value * weight
            total_weight += weight
        
        if total_weight > 0:
            return weighted_sum / total_weight
        
        return 0.0
    
    def _categorize_weight(self, weight: float) -> str:
        """
        Определить категорию по весу
        
        Args:
            weight: Вес ордера
            
        Returns:
            Категория: basic, gold, diamond
        """
        from config.main_config import WEIGHT_CATEGORIES
        
        for category, bounds in WEIGHT_CATEGORIES.items():
            if bounds["min"] <= weight < bounds["max"]:
                return category
        
        # Если вес = 1.0, то diamond
        if weight >= WEIGHT_CATEGORIES["diamond"]["min"]:
            return "diamond"
        
        return "basic"
    
    def _categorize_weight(self, weight: float) -> str:
        """Определить категорию по весу (по спецификации: 0-0.333, 0.333-0.666, 0.666-1)"""
        from config.main_config import WEIGHT_CATEGORIES
        
        for category, bounds in WEIGHT_CATEGORIES.items():
            if bounds["min"] <= weight < bounds["max"]:
                return category
        
        # Если вес = 1.0, то diamond
        if weight >= WEIGHT_CATEGORIES["diamond"]["min"]:
            return "diamond"
        
        return "basic"
    
    def batch_calculate_weights(self, orders: List[dict], market_context: dict = None) -> List[dict]:
        """
        Рассчитать веса для списка ордеров
        
        Args:
            orders: Список ордеров
            market_context: Контекст рынка
            
        Returns:
            Список ордеров с рассчитанными весами
        """
        results = []
        
        for order in orders:
            try:
                weight_data = self.calculate_order_weight(order, market_context)
                
                # Добавляем данные весов к ордеру
                enhanced_order = order.copy()
                enhanced_order.update(weight_data)
                
                results.append(enhanced_order)
                
            except Exception as e:
                self.logger.error("Error calculating weight for order",
                                order_hash=order.get("order_hash"),
                                error=str(e))
                # Добавляем ордер с нулевыми весами
                enhanced_order = order.copy()
                enhanced_order.update({
                    "weights": {"recommended": 0.0},
                    "categories": {"recommended": "basic"}
                })
                results.append(enhanced_order)
        
        return results
