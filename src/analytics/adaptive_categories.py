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
        """
        Рассчитать адаптивные пороги на основе статистики ордеров
        
        Args:
            order_values: Список USD стоимостей найденных ордеров
            
        Returns:
            Словарь с порогами и метаданными
        """
        if len(order_values) < 3:
            # Фаллбэк к статичным порогам если ордеров мало
            return self._get_static_thresholds()
        
        # Сортируем значения
        sorted_values = sorted(order_values)
        
        # Вычисляем статистики
        stats = {
            "min": min(sorted_values),
            "max": max(sorted_values),
            "median": statistics.median(sorted_values),
            "mean": statistics.mean(sorted_values),
            "count": len(sorted_values)
        }
        
        # Вычисляем перцентили
        q25 = self._percentile(sorted_values, 25)  # 1-я квартиль
        q50 = stats["median"]                       # 2-я квартиль (медиана)
        q75 = self._percentile(sorted_values, 75)  # 3-я квартиль
        q90 = self._percentile(sorted_values, 90)  # 90-й перцентиль
        
        # Метод 1: Квартильная система
        quartile_thresholds = {
            "basic": {"min": 0, "max": q50},
            "gold": {"min": q50, "max": q75}, 
            "diamond": {"min": q75, "max": float('inf')}
        }
        
        # Метод 2: Статистическая система (среднее + стандартное отклонение)
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
        
        # Метод 3: Процентильная система 
        percentile_thresholds = {
            "basic": {"min": 0, "max": q75},
            "gold": {"min": q75, "max": q90},
            "diamond": {"min": q90, "max": float('inf')}
        }
        
        # Выбираем метод на основе распределения данных
        selected_method, selected_thresholds = self._select_best_method(
            sorted_values, quartile_thresholds, statistical_thresholds, percentile_thresholds
        )
        
        self.logger.info(f"Using {selected_method} thresholds",
                        basic_max=selected_thresholds["basic"]["max"],
                        gold_max=selected_thresholds["gold"]["max"],
                        diamond_min=selected_thresholds["diamond"]["min"])
        
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


# Интеграция в PrimaryScanner
def integrate_adaptive_categories():
    """Пример интеграции в PrimaryScanner"""
    
    # В методе _get_scan_results класса PrimaryScanner:
    
    def _get_scan_results_adaptive(self) -> Dict:
        """Получение результатов сканирования с адаптивными категориями"""
        duration = 0
        if self.scan_start_time:
            end_time = self.scan_end_time or datetime.now(timezone.utc)
            duration = (end_time - self.scan_start_time).total_seconds()
        
        # Сортируем ордера по размеру
        sorted_orders = sorted(self.found_orders, key=lambda x: x.usd_value, reverse=True)
        
        # Адаптивная категоризация
        categorizer = AdaptiveCategorizer()
        order_values = [order.usd_value for order in self.found_orders]
        adaptive_data = categorizer.calculate_adaptive_thresholds(order_values)
        
        # Категоризируем ордера
        order_dicts = [self._order_to_dict(order) for order in self.found_orders]
        categories = categorizer.categorize_orders(order_dicts, adaptive_data)
        
        return {
            "scan_completed": True,
            "scan_start_time": self.scan_start_time.isoformat() if self.scan_start_time else None,
            "scan_end_time": self.scan_end_time.isoformat() if self.scan_end_time else None,
            "duration_seconds": duration,
            "total_symbols_scanned": self.scanned_symbols,
            "total_large_orders": self.total_large_orders,
            "orders_by_symbol": self.orders_by_symbol,
            "top_orders": [self._order_to_dict(order) for order in sorted_orders[:10]],
            
            # Адаптивная статистика
            "adaptive_categories": {
                "method": adaptive_data["method"],
                "thresholds": adaptive_data["thresholds"],
                "distribution": {
                    "diamond": len(categories["diamond"]),
                    "gold": len(categories["gold"]),
                    "basic": len(categories["basic"])
                },
                "categories": categories
            },
            
            "statistics": {
                **adaptive_data.get("stats", {}),
                "percentiles": adaptive_data.get("percentiles", {}),
                "symbols_with_orders": len(self.orders_by_symbol),
                "round_level_orders": len([o for o in self.found_orders if o.is_round_level])
            }
        }
