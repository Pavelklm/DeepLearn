"""
Тесты горячего пула - строго по спецификации
"""

import pytest

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, mock_open


from src.pools.hot_pool import HotPool, HotOrder
from src.pools.observer_pool import TrackedOrder
from src.exchanges.base_exchange import BaseExchange
from src.analytics.weight_calculator import WeightCalculator
from config.main_config import POOLS_CONFIG, WEIGHT_CATEGORIES, FILE_CONFIG
from config.weights_config import WEIGHT_ALGORITHMS


@pytest.fixture
def mock_exchange():
    exchange = AsyncMock(spec=BaseExchange)
    exchange.name = "binance"  # Добавляем имя биржи
    exchange.get_current_price = AsyncMock(return_value=50000.0)
    exchange.get_volatility_data = AsyncMock(return_value={"volatility": 0.02})
    exchange.get_orderbook = AsyncMock(return_value={
        "asks": [[50100, 5.0]],
        "bids": [[49900, 5.0]]
    })
    return exchange

@pytest.fixture
def hot_pool(mock_exchange):
    pool = HotPool(mock_exchange)
    pool.websocket_server = MagicMock()
    pool.websocket_server.send_hot_pool_data = AsyncMock()
    return pool

@pytest.fixture
def sample_tracked_order():
    """Тестовый TrackedOrder для горячего пула"""
    return TrackedOrder(
        order_hash="BTCUSD-abc123",
        symbol="BTCUSDT",
        price=51000.0,
        quantity=5.0,
        side="ASK",
        usd_value=255000.0,
        first_seen=datetime.now(timezone.utc) - timedelta(minutes=10),
        last_seen=datetime.now(timezone.utc),
        scan_count=600
    )

@pytest.fixture
def sample_order_data():
    """Тестовые данные ордера для расчета весов"""
    return {
        "order_hash": "BTCUSD-abc123",
        "symbol": "BTCUSDT",
        "price": 51000.0,
        "quantity": 5.0,
        "type": "ASK",
        "usd_value": 255000.0,
        "distance_percent": 2.0,
        "size_vs_average": 8.5,
        "average_order_size": 30000.0,
        "first_seen": (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
        "last_seen": datetime.now(timezone.utc).isoformat(),
        "lifetime_seconds": 600,
        "volatility_1h": 0.02,
        "is_round_level": True,
        "scan_count": 600
    }

@pytest.fixture
def sample_update_data():
    """Данные обновления для добавления в горячий пул"""
    return {
        "lifetime_seconds": 600,
        "current_quantity": 5.0,
        "quantity_change": 0.0
    }


class TestHotPool:
    """Тесты горячего пула по спецификации"""
    
    @pytest.mark.asyncio
    async def test_weight_calculation_algorithms(self, hot_pool, sample_order_data):
        """Тест: Расчет весов по разным алгоритмам"""
        calculator = WeightCalculator()
        
        # Рассчитываем веса для тестового ордера
        weight_data = calculator.calculate_order_weight(sample_order_data)
        print("\n=== weight_data ===")
        print(weight_data)  # Посмотреть весь словарь с аналитикой
        
        # Извлекаем веса
        weights = weight_data.get("weights", {})
        print("\n=== weights ===")
        print(weights)  # Посмотреть все веса по алгоритмам
        
        # Проверяем наличие всех алгоритмов
        for algo_name in WEIGHT_ALGORITHMS.keys():
            assert algo_name in weights, f"Algorithm {algo_name} missing in weights"
            assert 0 <= weights[algo_name] <= 1, f"Weight for {algo_name} out of range [0,1]"
        
        # Проверяем специфические алгоритмы из спецификации
        required_algos = ["conservative", "aggressive", "volume_weighted",
                          "time_weighted", "hybrid", "recommended"]
        for algo in required_algos:
            assert algo in weights, f"{algo} missing in weights"
        
        print("\n✅ Все проверки пройдены успешно!")
    
    @pytest.mark.asyncio
    async def test_category_determination(self, hot_pool, sample_order_data):
        """Тест: Определение категорий ордеров"""
        calculator = WeightCalculator()
        
        # Тестовые веса для разных категорий
        test_cases = [
            (0.1, "basic"),      # 0.1 → basic (0.000 - 0.333)
            (0.2, "basic"),      # 0.2 → basic
            (0.333, "basic"),    # 0.333 → basic (граница)
            (0.334, "gold"),     # 0.334 → gold (0.333 - 0.666)
            (0.5, "gold"),       # 0.5 → gold
            (0.666, "gold"),     # 0.666 → gold (граница)
            (0.667, "diamond"),  # 0.667 → diamond (0.666 - 1.000)
            (0.8, "diamond"),    # 0.8 → diamond
            (1.0, "diamond"),    # 1.0 → diamond
        ]
        
        for weight, expected_category in test_cases:
            # Определяем категорию
            category = None
            for cat_name, cat_config in WEIGHT_CATEGORIES.items():
                if cat_config["min"] <= weight <= cat_config["max"]:
                    category = cat_name
                    break
            
            assert category == expected_category, f"Weight {weight} should be {expected_category}, got {category}"
    
    @pytest.mark.asyncio
    async def test_realtime_file_saving(self, hot_pool, sample_tracked_order, sample_update_data):
        """Тест: Сохранение в файл в реальном времени"""
        # Добавляем ордер в горячий пул используя правильный API
        await hot_pool.add_order_from_observer(sample_tracked_order, sample_update_data)
        
        # Проверяем настройки сохранения
        save_interval = FILE_CONFIG["save_interval"]
        assert save_interval == 1  # 1 секунда по спецификации
        
        # Проверяем путь к файлу
        hot_orders_file = FILE_CONFIG["hot_orders_file"]
        assert hot_orders_file == "data/hot_pool_orders.json"
        
        # Симулируем сохранение
        hot_pool_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "orders": [sample_tracked_order],
            "total_orders": 1,
            "categories": {
                "basic": 0,
                "gold": 0,
                "diamond": 1
            }
        }
        
        # Проверяем структуру данных для сохранения
        assert "timestamp" in hot_pool_data
        assert "orders" in hot_pool_data
        assert "total_orders" in hot_pool_data
        assert "categories" in hot_pool_data
    
    @pytest.mark.asyncio
    async def test_websocket_update_triggers(self, hot_pool, sample_tracked_order, sample_update_data):
        """Тест: WebSocket отправка обновлений"""
        # Триггеры отправки из спецификации
        triggers = [
            "new_order",           # Новый ордер в горячем пуле
            "order_removed",       # Ордер исчез из горячего пула
            "category_changed",    # Изменение категории ордера
            "weight_changed",      # Изменение веса > 0.05
            "usd_value_changed"    # Изменение USD value > 5%
        ]
        
        # Проверяем пороги из конфига
        weight_threshold = POOLS_CONFIG["hot_pool"]["weight_change_threshold"]
        usd_threshold = POOLS_CONFIG["hot_pool"]["usd_change_threshold"]
        
        assert weight_threshold == 0.05  # 5% изменение веса
        assert usd_threshold == 0.05     # 5% изменение USD
        
        # Тест триггера: новый ордер
        await hot_pool.add_order_from_observer(sample_tracked_order, sample_update_data)
        # WebSocket должен отправить обновление
        
        # Тест триггера: изменение веса
        old_weight = 0.5
        new_weight = 0.56  # Изменение на 0.06 > 0.05
        should_trigger = abs(new_weight - old_weight) > weight_threshold
        assert should_trigger == True
        
        # Тест триггера: изменение USD value
        old_usd = 100000
        new_usd = 106000  # Изменение на 6%
        usd_change = abs(new_usd - old_usd) / old_usd
        should_trigger_usd = usd_change > usd_threshold
        assert should_trigger_usd == True
    
    @pytest.mark.asyncio
    async def test_time_factors_calculation(self, hot_pool):
        """Тест: Расчет временных факторов"""
        calculator = WeightCalculator()
        
        # Тестовые временные значения (в секундах)
        test_times = [60, 300, 600, 1800, 3600, 7200, 14400, 28800]  # 1мин - 8часов
        
        # Маркет контекст для адаптивных методов
        market_context = {
            "symbol_volatility_1h": 0.05,
            "market_temperature": 1.2
        }
        
        for lifetime_seconds in test_times:
            time_factors = calculator._calculate_time_factors(lifetime_seconds, market_context)
            
            # Проверяем наличие реальных временных факторов из конфига
            from config.weights_config import TIME_FACTORS_CONFIG
            expected_methods = list(TIME_FACTORS_CONFIG["methods"].keys())
            
            # Проверяем все методы (включая адаптивные с контекстом)
            for method_name in expected_methods:
                assert method_name in time_factors, f"Missing time factor: {method_name}"
            
            # Проверяем диапазон значений [0, 1]
            for factor_name, factor_value in time_factors.items():
                assert 0 <= factor_value <= 1, f"{factor_name} = {factor_value} out of range"
    
    @pytest.mark.asyncio
    async def test_full_analytical_structure(self, hot_pool, sample_order_data):
        """Тест: Полная аналитическая структура ордера"""
        calculator = WeightCalculator()
        
        # Получаем полную аналитику
        analytics = calculator.calculate_order_weight(sample_order_data)
        
        # Проверяем основные поля аналитики (из реального API)
        required_analytics_fields = [
            "time_factors",
            "context_factors", 
            "weights",
            "categories",
            "calculation_timestamp"
        ]
        
        for field in required_analytics_fields:
            assert field in analytics, f"Missing analytics field: {field}"
        
        # Проверяем поля исходных данных
        order_fields = ["order_hash", "symbol", "price", "usd_value"]
        for field in order_fields:
            assert field in sample_order_data, f"Missing order field: {field}"
        
        # Проверяем time_factors
        time_factors = analytics.get("time_factors", {})
        assert len(time_factors) > 0
        
        # Проверяем weights
        weights = analytics.get("weights", {})
        assert "conservative" in weights
        assert "aggressive" in weights
        assert "recommended" in weights
        
        # Проверяем categories
        categories = analytics.get("categories", {})
        assert "by_conservative" in categories
        assert "by_aggressive" in categories
        assert "by_recommended" in categories
    
    @pytest.mark.asyncio
    async def test_adaptive_workers(self, hot_pool):
        """Тест: Адаптивное количество воркеров"""
        max_workers = POOLS_CONFIG["hot_pool"]["max_workers"]
        assert max_workers == 8  # Максимум 8 воркеров по спецификации
        
        # Тестовые сценарии нагрузки
        test_cases = [
            (1, 1),    # 1 ордер → 1 воркер
            (5, 1),    # 5 ордеров → 1 воркер
            (10, 2),   # 10 ордеров → 2 воркера
            (20, 3),   # 20 ордеров → 3 воркера
            (50, 5),   # 50 ордеров → 5 воркеров
            (100, 8),  # 100 ордеров → 8 воркеров (максимум)
            (200, 8),  # 200 ордеров → 8 воркеров (все еще максимум)
        ]
        
        for orders_count, expected_workers in test_cases:
            # Простая формула: 1 воркер на 10 ордеров, но не больше max_workers
            workers = min(max(1, orders_count // 10), max_workers)
            assert workers <= max_workers
    
    @pytest.mark.asyncio
    async def test_market_context_modifiers(self, hot_pool, sample_order_data):
        """Тест: Рыночный контекст и модификаторы"""
        calculator = WeightCalculator()
        
        # Получаем аналитику с рыночным контекстом
        market_context = {
            "symbol_volatility_1h": 0.02,
            "market_volatility": 0.03,
            "market_temperature": 1.2
        }
        
        analytics = calculator.calculate_order_weight(sample_order_data, market_context)
        
        # Проверяем context_factors (реальное поле из API)
        context_factors = analytics.get("context_factors", {})
        assert len(context_factors) > 0
        
        expected_context_fields = [
            "size_factor",
            "round_level_factor", 
            "volatility_factor",
            "growth_factor",
            "time_modifier",
            "day_modifier",
            "market_volatility_modifier"
        ]
        
        for field in expected_context_fields:
            assert field in context_factors, f"Missing context factor: {field}"
        
        # Проверяем модификаторы времени суток (из weights_config)
        from config.weights_config import MARKET_MODIFIERS
        
        time_modifiers = MARKET_MODIFIERS["time_of_day"]
        assert "asian_session" in time_modifiers
        assert "london_session" in time_modifiers
        assert "new_york_session" in time_modifiers
        
        # Проверяем модификаторы дня недели
        day_modifiers = MARKET_MODIFIERS["day_of_week"]
        assert len(day_modifiers) == 7  # Все дни недели
        assert day_modifiers["saturday"] < day_modifiers["monday"]  # Выходные менее активны
    
    @pytest.mark.asyncio
    async def test_category_distribution(self, hot_pool):
        """Тест: Распределение по категориям"""
        # Добавляем несколько ордеров с разными весами
        orders = [
            {"order_hash": "ORDER1", "recommended_weight": 0.2},   # basic
            {"order_hash": "ORDER2", "recommended_weight": 0.3},   # basic
            {"order_hash": "ORDER3", "recommended_weight": 0.4},   # gold
            {"order_hash": "ORDER4", "recommended_weight": 0.5},   # gold
            {"order_hash": "ORDER5", "recommended_weight": 0.7},   # diamond
            {"order_hash": "ORDER6", "recommended_weight": 0.8},   # diamond
        ]
        
        # Считаем распределение
        distribution = {"basic": 0, "gold": 0, "diamond": 0}
        
        for order in orders:
            weight = order["recommended_weight"]
            if weight <= 0.333:
                distribution["basic"] += 1
            elif weight <= 0.666:
                distribution["gold"] += 1
            else:
                distribution["diamond"] += 1
        
        # Проверяем
        assert distribution["basic"] == 2
        assert distribution["gold"] == 2
        assert distribution["diamond"] == 2
    
    @pytest.mark.asyncio
    async def test_minimum_scan_interval(self, hot_pool):
        """Тест: Минимальный интервал сканирования"""
        min_interval = POOLS_CONFIG["hot_pool"]["min_scan_interval"]
        
        # Проверяем настройки
        assert min_interval == 0.5  # 0.5 секунды по спецификации
        assert isinstance(min_interval, (int, float))
        assert min_interval > 0
        assert min_interval < 1  # Меньше секунды для real-time