"""
Адаптивная система категорий ордеров на основе статистики
"""

import statistics
from typing import List, Dict
from src.utils.logger import get_component_logger

logger = get_component_logger("adaptive_categories")


class AdaptiveCategorizer:
    """Адаптивная категоризация ордеров на основе их распределения"""
    
    def __init__(self):
        self.logger = logger
        
    def calculate_adaptive_thresholds(self, order_values: List[float]) -> Dict[str, Dict]:
        if len(order_values) < 3:
            return self._get_static_thresholds()
        
        sorted_values = sorted(order_values)
        stats = {
            "min": min(sorted_values),
            "max": max(sorted_values),
            "median": statistics.median(sorted_values),
            "mean": statistics.mean(sorted_values),
            "count": len(sorted_values)
        }
        
        q25 = self._percentile(sorted_values, 25)
        q50 = stats["median"]
        q75 = self._percentile(sorted_values, 75)
        q90 = self._percentile(sorted_values, 90)
        
        quartile_thresholds = {
            "basic": {"min": 0, "max": q50},
            "gold": {"min": q50, "max": q75}, 
            "diamond": {"min": q75, "max": float('inf')}
        }
        
        if len(sorted_values) > 1:
            std_dev = statistics.stdev(sorted_values)
            mean = stats["mean"]
            statistical_thresholds = {
                "basic": {"min": 0, "max": mean},
                "gold": {"min": mean, "max": mean + std_dev},
                "diamond": {"min": mean + std_dev, "max": float('inf')}
            }
        else:
            statistical_thresholds = quartile_thresholds
        
        percentile_thresholds = {
            "basic": {"min": 0, "max": q75},
            "gold": {"min": q75, "max": q90},
            "diamond": {"min": q90, "max": float('inf')}
        }
        
        selected_method, selected_thresholds = self._select_best_method(
            sorted_values, quartile_thresholds, statistical_thresholds, percentile_thresholds
        )
        
        # Логируем безопасно через форматированную строку
        self.logger.info(
            f"Using {selected_method} thresholds | "
            f"basic_max={selected_thresholds['basic']['max']}, "
            f"gold_max={selected_thresholds['gold']['max']}, "
            f"diamond_min={selected_thresholds['diamond']['min']}"
        )
        
        return {
            "method": selected_method,
            "thresholds": selected_thresholds,
            "stats": stats,
            "percentiles": {"q25": q25, "q50": q50, "q75": q75, "q90": q90},
            "all_methods": {
                "quartile": quartile_thresholds,
                "statistical": statistical_thresholds,
                "percentile": percentile_thresholds
            }
        }
    
    def _select_best_method(self, values, quartile, statistical, percentile):
        """Выбрать лучший метод на основе характеристик распределения"""
        
        # Проверяем равномерность распределения
        q25 = self._percentile(values, 25)
        q75 = self._percentile(values, 75)
        iqr = q75 - q25
        
        range_val = max(values) - min(values)
        
        # Если большой разброс - используем процентильную систему
        if range_val > iqr * 5:
            return "percentile", percentile
        
        # Если значения близки к нормальному распределению - статистическую
        mean = statistics.mean(values)
        median = statistics.median(values)
        
        if abs(mean - median) / mean < 0.2:  # Разница меньше 20%
            return "statistical", statistical
        
        # По умолчанию - квартильную
        return "quartile", quartile
    
    def _percentile(self, values: List[float], percentile: float) -> float:
        """Вычислить перцентиль"""
        if not values:
            return 0.0
        
        k = (len(values) - 1) * (percentile / 100.0)
        f = int(k)
        c = k - f
        
        if f == len(values) - 1:
            return values[f]
        
        return values[f] * (1 - c) + values[f + 1] * c
    
    def _get_static_thresholds(self) -> Dict:
        """Статичные пороги как фаллбэк"""
        return {
            "method": "static_fallback",
            "thresholds": {
                "basic": {"min": 0, "max": 5000},
                "gold": {"min": 5000, "max": 15000},
                "diamond": {"min": 15000, "max": float('inf')}
            },
            "stats": None
        }
    
    def categorize_orders(self, orders: List[Dict], thresholds: Dict) -> Dict:
        """Категоризировать ордера по адаптивным порогам"""
        categories = {"basic": [], "gold": [], "diamond": []}
        
        for order in orders:
            usd_value = order.get("usd_value", 0)
            
            for category, bounds in thresholds["thresholds"].items():
                if bounds["min"] <= usd_value < bounds["max"]:
                    categories[category].append(order)
                    break
        
        return categories


