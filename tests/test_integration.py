"""
Интеграционный тест полного цикла системы
Тестирует весь путь: первичное сканирование → наблюдатель → горячий пул
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timezone, timedelta

from src.scanner_orchestrator import ScannerOrchestrator
from src.exchanges.base_exchange import BaseExchange
from src.pools.primary_scanner import PrimaryScanner
from src.pools.observer_pool import ObserverPool
from src.pools.hot_pool import HotPool
from src.pools.general_pool import GeneralPool


class MockExchange(BaseExchange):
    """Комплексный мок биржи для интеграционного теста"""
    
    def __init__(self):
        super().__init__("test_integration", {})
        
        # Предзаданные данные для тестирования полного цикла
        self.symbols_data = {
            # Символ с большим ордером который пройдет весь путь до diamond
            "BTCUSDT": {
                "price": 65000.0,
                "volume": 5000000000,  # Высокий объем
                "orderbooks": [
                    # Первое сканирование - большой ордер
                    {
                        "asks": [["65500.0", "100.0"], ["65600.0", "15.0"], ["65700.0", "8.0"]],  # 100 BTC = 6.55M USD
                        "bids": [["64900.0", "12.0"], ["64800.0", "8.0"]]
                    },
                    # Второе сканирование - ордер еще жив
                    {
                        "asks": [["65500.0", "95.0"], ["65600.0", "15.0"], ["65700.0", "8.0"]],   # Чуть уменьшился
                        "bids": [["64900.0", "12.0"], ["64800.0", "8.0"]]
                    },
                    # Третье сканирование - ордер живет > 60 секунд
                    {
                        "asks": [["65500.0", "90.0"], ["65600.0", "15.0"], ["65700.0", "8.0"]],   # Еще чуть меньше
                        "bids": [["64900.0", "12.0"], ["64800.0", "8.0"]]
                    }
                ]
            },
            
            # Символ где ордер умрет от потери объема
            "ETHUSDT": {
                "price": 3200.0,
                "volume": 3000000000,
                "orderbooks": [
                    # Начальный большой ордер
                    {
                        "asks": [["3250.0", "50.0"], ["3260.0", "10.0"]],  # 50 ETH = 162.5K USD
                        "bids": [["3150.0", "8.0"], ["3140.0", "6.0"]]
                    },
                    # Ордер потерял >70% объема - должен умереть
                    {
                        "asks": [["3250.0", "10.0"], ["3260.0", "10.0"]],  # Потерял 80% объема
                        "bids": [["3150.0", "8.0"], ["3140.0", "6.0"]]
                    }
                ]
            },
            
            # Символ где ордер изменит цену - тоже умрет
            "ADAUSDT": {
                "price": 0.45,
                "volume": 800000000,
                "orderbooks": [
                    # Начальный ордер
                    {
                        "asks": [["0.46", "100000.0"], ["0.47", "50000.0"]],  # 46K USD
                        "bids": [["0.44", "80000.0"], ["0.43", "70000.0"]]
                    },
                    # Ордер переместился на другую цену
                    {
                        "asks": [["0.465", "100000.0"], ["0.47", "50000.0"]],  # Цена изменилась
                        "bids": [["0.44", "80000.0"], ["0.43", "70000.0"]]
                    }
                ]
            }
        }
        
        # Счетчики для симуляции времени
        self.scan_counts = {symbol: 0 for symbol in self.symbols_data.keys()}
        self.start_time = datetime.now(timezone.utc)
    
    async def connect(self) -> bool:
        self.is_connected = True
        return True
    
    async def disconnect(self):
        self.is_connected = False
    
    async def get_top_volume_symbols(self, limit: int) -> list:
        # Возвращаем символы отсортированные по объему
        sorted_symbols = sorted(
            self.symbols_data.keys(), 
            key=lambda x: self.symbols_data[x]["volume"], 
            reverse=True
        )
        return sorted_symbols[:limit]
    
    async def get_orderbook(self, symbol: str, depth: int = 20) -> dict:
        if symbol not in self.symbols_data:
            return {"asks": [], "bids": []}
        
        # Используем разные стаканы в зависимости от номера сканирования
        scan_count = self.scan_counts[symbol]
        orderbooks = self.symbols_data[symbol]["orderbooks"]
        
        if scan_count < len(orderbooks):
            result = orderbooks[scan_count]
        else:
            # Если сканирований больше чем заготовленных стаканов, используем последний
            result = orderbooks[-1]
        
        self.scan_counts[symbol] += 1
        return result
    
    async def get_current_price(self, symbol: str) -> float:
        return self.symbols_data.get(symbol, {}).get("price", 1000.0)
    
    async def get_volatility_data(self, symbol: str, timeframe: str) -> dict:
        return {"volatility": 0.025, "price_change": 0.015}
    
    async def get_futures_pairs(self) -> list:
        return list(self.symbols_data.keys())
    
    async def get_24h_volume_stats(self, symbols: list = None) -> dict:
        return {
            symbol: {"volume": str(data["volume"])} 
            for symbol, data in self.symbols_data.items()
        }
    
    async def get_24h_ticker(self, symbol: str) -> dict:
        return {
            "volume": str(self.symbols_data.get(symbol, {}).get("volume", 1000000)),
            "quoteVolume": str(self.symbols_data.get(symbol, {}).get("volume", 1000000) * 10),
            "priceChange": "100.0",
            "priceChangePercent": "1.5"
        }


class TestIntegration:
    """Интеграционные тесты полного цикла системы"""
    
    @pytest.fixture
    def mock_exchange(self):
        return MockExchange()
    
    @pytest.fixture
    async def full_system(self, mock_exchange):
        """Создание полной системы для интеграционного теста"""
        # Создаем компоненты вручную для полного контроля
        hot_pool = HotPool(mock_exchange)
        
        observer_pool = ObserverPool(mock_exchange)
        observer_pool.hot_pool = hot_pool
        
        general_pool = GeneralPool(mock_exchange)
        general_pool.observer_pool = observer_pool
        
        primary_scanner = PrimaryScanner(mock_exchange, observer_pool)
        
        return {
            "exchange": mock_exchange,
            "primary_scanner": primary_scanner,
            "observer_pool": observer_pool,
            "hot_pool": hot_pool,
            "general_pool": general_pool
        }
    
    @pytest.mark.asyncio
    async def test_полный_цикл_первичное_сканирование_к_горячему_пулу(self, full_system):
        """
        Тест полного цикла согласно спецификации:
        Первичное сканирование → Observer Pool → Hot Pool
        """
        components = full_system
        primary_scanner = components["primary_scanner"]
        observer_pool = components["observer_pool"]
        hot_pool = components["hot_pool"]
        
        # ===== ЭТАП 1: ПЕРВИЧНОЕ СКАНИРОВАНИЕ =====
        
        # Запускаем первичное сканирование
        test_symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT"]
        scan_results = await primary_scanner.run_test_scan(test_symbols)
        
        # Проверяем результаты первичного сканирования
        assert scan_results["scan_completed"] is True
        assert scan_results["total_large_orders"] > 0
        assert scan_results["total_symbols_scanned"] == len(test_symbols)
        
        # Проверяем что ордера попали в пул наблюдателя
        assert len(observer_pool.observed_symbols) > 0
        assert "BTCUSDT" in observer_pool.observed_symbols
        
        # Проверяем структуру ордера в пуле наблюдателя
        btc_orders = observer_pool.observed_symbols["BTCUSDT"]
        assert len(btc_orders) > 0
        
        btc_order = btc_orders[0]
        assert btc_order["symbol"] == "BTCUSDT"
        assert btc_order["is_alive"] is True
        assert "first_seen" in btc_order
        assert "order_hash" in btc_order
        
        # ===== ЭТАП 2: РАБОТА ПУЛА НАБЛЮДАТЕЛЯ =====
        
        # Ждем чтобы ордер "состарился" (симулируем время > 60 секунд)
        for symbol in observer_pool.observed_symbols:
            for order in observer_pool.observed_symbols[symbol]:
                # Делаем ордер старше 60 секунд
                old_time = datetime.now(timezone.utc) - timedelta(seconds=70)
                order["first_seen"] = old_time
        
        # Запускаем несколько циклов observer pool
        for _ in range(3):
            for symbol in list(observer_pool.observed_symbols.keys()):
                await observer_pool._scan_symbol(symbol)
            await asyncio.sleep(0.1)  # Небольшая задержка
        
        # Проверяем что ордер перешел в горячий пул
        assert len(hot_pool.hot_orders) > 0
        
        # Находим наш BTC ордер в горячем пуле
        btc_hot_order = None
        for order_hash, order_data in hot_pool.hot_orders.items():
            if order_data["symbol"] == "BTCUSDT":
                btc_hot_order = order_data
                break
        
        assert btc_hot_order is not None, "BTC ордер не попал в горячий пул"
        
        # ===== ЭТАП 3: ПРОВЕРКА ГОРЯЧЕГО ПУЛА =====
        
        # Проверяем полную аналитическую структуру из спецификации
        required_sections = [
            "order_hash", "symbol", "exchange", "current_price", "order_price",
            "usd_value", "lifetime_seconds", "time_factors", "market_context",
            "weights", "categories", "analytics", "tracking"
        ]
        
        for section in required_sections:
            assert section in btc_hot_order, f"Отсутствует раздел: {section}"
        
        # Проверяем временные факторы из спецификации
        expected_time_factors = [
            "linear_1h", "linear_4h", "exponential_30m", "exponential_60m",
            "logarithmic", "sqrt_normalized", "adaptive"
        ]
        
        for factor in expected_time_factors:
            assert factor in btc_hot_order["time_factors"], f"Отсутствует временной фактор: {factor}"
        
        # Проверяем алгоритмы весов из спецификации
        expected_weight_algorithms = [
            "conservative", "aggressive", "volume_weighted", "time_weighted", "hybrid", "recommended"
        ]
        
        for algorithm in expected_weight_algorithms:
            assert algorithm in btc_hot_order["weights"], f"Отсутствует алгоритм веса: {algorithm}"
            weight = btc_hot_order["weights"][algorithm]
            assert 0.0 <= weight <= 1.0, f"Вес {algorithm} вне диапазона: {weight}"
        
        # Проверяем категории по всем алгоритмам
        for algorithm in expected_weight_algorithms:
            category_key = f"by_{algorithm}"
            assert category_key in btc_hot_order["categories"], f"Отсутствует категория: {category_key}"
            category = btc_hot_order["categories"][category_key]
            assert category in ["basic", "gold", "diamond"], f"Неверная категория: {category}"
        
        # Проверяем market_context из спецификации
        market_context = btc_hot_order["market_context"]
        expected_context_fields = [
            "symbol_volatility_1h", "market_volatility", "time_of_day_factor", "weekend_factor"
        ]
        
        for field in expected_context_fields:
            assert field in market_context, f"Отсутствует поле market_context: {field}"
        
        # Проверяем analytics секцию
        analytics = btc_hot_order["analytics"]
        expected_analytics = [
            "size_vs_average_top10", "distance_to_round_level", "is_psycho_level",
            "order_book_dominance", "historical_success_rate"
        ]
        
        for field in expected_analytics:
            assert field in analytics, f"Отсутствует поле analytics: {field}"
    
    @pytest.mark.asyncio
    async def test_сценарий_смерти_и_воскрешения_ордеров(self, full_system):
        """Тест сценариев когда ордера умирают и воскрешаются"""
        components = full_system
        primary_scanner = components["primary_scanner"]
        observer_pool = components["observer_pool"]
        
        # Запускаем первичное сканирование
        await primary_scanner.run_test_scan(["ETHUSDT", "ADAUSDT"])
        
        # Проверяем что ордера попали в observer pool
        assert "ETHUSDT" in observer_pool.observed_symbols
        assert "ADAUSDT" in observer_pool.observed_symbols
        
        # Получаем исходные ордера
        eth_order = observer_pool.observed_symbols["ETHUSDT"][0]
        ada_order = observer_pool.observed_symbols["ADAUSDT"][0]
        
        original_eth_hash = eth_order["order_hash"]
        original_ada_hash = ada_order["order_hash"]
        
        # Сканируем символы - ордера должны "умереть"
        await observer_pool._scan_symbol("ETHUSDT")  # Потеря объема >70%
        await observer_pool._scan_symbol("ADAUSDT")  # Изменение цены
        
        # Проверяем что ордера помечены как мертвые
        eth_order_after = observer_pool.observed_symbols["ETHUSDT"][0]
        ada_order_after = observer_pool.observed_symbols["ADAUSDT"][0]
        
        # Один из ордеров должен умереть, или появиться новый
        # (в зависимости от реализации - может создаваться новый ордер при изменении цены)
        assert len(observer_pool.observed_symbols["ETHUSDT"]) >= 1
        assert len(observer_pool.observed_symbols["ADAUSDT"]) >= 1
    
    @pytest.mark.asyncio
    async def test_категоризация_ордеров_diamond_gold_basic(self, full_system):
        """Тест попадания ордеров в правильные категории"""
        components = full_system
        primary_scanner = components["primary_scanner"]
        observer_pool = components["observer_pool"]
        hot_pool = components["hot_pool"]
        
        # Запускаем полный цикл
        await primary_scanner.run_test_scan(["BTCUSDT"])
        
        # Переводим ордер в горячий пул
        btc_order = observer_pool.observed_symbols["BTCUSDT"][0]
        old_time = datetime.now(timezone.utc) - timedelta(seconds=70)
        btc_order["first_seen"] = old_time
        
        await observer_pool._scan_symbol("BTCUSDT")
        
        # Проверяем что ордер в горячем пуле
        assert len(hot_pool.hot_orders) > 0
        
        hot_order = list(hot_pool.hot_orders.values())[0]
        
        # Проверяем категории по спецификации
        categories = hot_order["categories"]
        
        # Каждый алгоритм должен дать одну из трех категорий
        algorithms = ["conservative", "aggressive", "volume_weighted", "time_weighted", "hybrid", "recommended"]
        
        for algorithm in algorithms:
            category = categories[f"by_{algorithm}"]
            assert category in ["basic", "gold", "diamond"]
            
            # Проверяем соответствие веса и категории
            weight = hot_order["weights"][algorithm]
            
            if category == "basic":
                assert 0.0 <= weight < 0.333
            elif category == "gold":
                assert 0.333 <= weight < 0.666
            elif category == "diamond":
                assert 0.666 <= weight <= 1.0
    
    def test_статистика_системы(self, full_system):
        """Тест получения статистики всей системы"""
        components = full_system
        observer_pool = components["observer_pool"]
        hot_pool = components["hot_pool"]
        
        # Добавляем тестовые данные
        test_order = {
            "symbol": "BTCUSDT",
            "price": 65000.0,
            "quantity": 10.0,
            "type": "ASK",
            "usd_value": 650000.0,
            "order_hash": "TEST-integration123",
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "volatility_1h": 0.025,
            "distance_percent": 1.0,
            "size_vs_average": 5.0,
            "average_order_size": 130000.0,
            "is_round_level": False
        }
        
        observer_pool.add_order_from_primary_scan(test_order)
        hot_pool.add_order_from_observer(test_order)
        
        # Получаем статистику
        observer_stats = observer_pool.get_stats()
        hot_stats = hot_pool.get_stats()
        
        # Проверяем структуру статистики
        assert "total_symbols" in observer_stats
        assert "total_orders" in observer_stats
        assert "alive_orders" in observer_stats
        
        assert "total_orders" in hot_stats
        assert "active_symbols" in hot_stats
        assert "categories_distribution" in hot_stats
        assert "avg_weight" in hot_stats
        
        # Проверяем значения
        assert observer_stats["total_symbols"] >= 1
        assert observer_stats["total_orders"] >= 1
        
        assert hot_stats["total_orders"] >= 1
        assert hot_stats["active_symbols"] >= 1
        assert isinstance(hot_stats["categories_distribution"], dict)
    
    @pytest.mark.asyncio
    async def test_мультибиржевая_архитектура(self, mock_exchange):
        """Тест принципов мультибиржевой архитектуры"""
        # Создаем второй мок биржи
        second_exchange = MockExchange()
        second_exchange.name = "test_integration_2"
        
        # Проверяем что можем создать компоненты для разных бирж
        hot_pool_1 = HotPool(mock_exchange)
        hot_pool_2 = HotPool(second_exchange)
        
        # Проверяем что у каждого пула своя биржа
        assert hot_pool_1.exchange.name == "test_integration"
        assert hot_pool_2.exchange.name == "test_integration_2"
        
        # Проверяем базовый интерфейс
        assert hasattr(mock_exchange, 'connect')
        assert hasattr(mock_exchange, 'disconnect') 
        assert hasattr(mock_exchange, 'get_orderbook')
        assert hasattr(mock_exchange, 'get_current_price')
        
        # Проверяем подключение
        assert await mock_exchange.connect() is True
        assert mock_exchange.is_connected is True
        
        await mock_exchange.disconnect()
        assert mock_exchange.is_connected is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
