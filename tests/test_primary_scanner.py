"""
Тест первичного сканнера
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone

from src.pools.primary_scanner import PrimaryScanner
from src.exchanges.base_exchange import BaseExchange


class MockExchange(BaseExchange):
    """Мок биржи для тестирования"""
    
    def __init__(self):
        super().__init__("test", {})
        self.symbols_data = {
            "BTCUSDT": {
                "price": 65000.0,
                "orderbook": {
                    "asks": [
                        ["65100.0", "10.0"], ["65200.0", "15.0"], ["65300.0", "8.0"],
                        ["65400.0", "12.0"], ["65500.0", "20.0"], ["65600.0", "5.0"],
                        ["65700.0", "7.0"], ["65800.0", "25.0"], ["65900.0", "6.0"],
                        ["66000.0", "18.0"], ["66100.0", "100.0"]  # Большой ордер
                    ],
                    "bids": [
                        ["64900.0", "12.0"], ["64800.0", "8.0"], ["64700.0", "15.0"],
                        ["64600.0", "10.0"], ["64500.0", "22.0"], ["64400.0", "6.0"],
                        ["64300.0", "9.0"], ["64200.0", "14.0"], ["64100.0", "7.0"],
                        ["64000.0", "11.0"], ["63900.0", "150.0"]  # Большой ордер
                    ]
                }
            },
            "ETHUSDT": {
                "price": 3200.0,
                "orderbook": {
                    "asks": [
                        ["3205.0", "5.0"], ["3210.0", "8.0"], ["3215.0", "3.0"],
                        ["3220.0", "6.0"], ["3225.0", "10.0"], ["3230.0", "4.0"],
                        ["3235.0", "7.0"], ["3240.0", "12.0"], ["3245.0", "2.0"],
                        ["3250.0", "9.0"], ["3255.0", "50.0"]  # Большой ордер
                    ],
                    "bids": [
                        ["3195.0", "6.0"], ["3190.0", "4.0"], ["3185.0", "8.0"],
                        ["3180.0", "5.0"], ["3175.0", "11.0"], ["3170.0", "3.0"],
                        ["3165.0", "7.0"], ["3160.0", "9.0"], ["3155.0", "4.0"],
                        ["3150.0", "6.0"], ["3145.0", "40.0"]  # Большой ордер
                    ]
                }
            }
        }
    
    async def connect(self) -> bool:
        """Реализация абстрактного метода connect"""
        self.is_connected = True
        return True
    
    async def disconnect(self):
        """Реализация абстрактного метода disconnect"""
        self.is_connected = False
    
    async def get_top_volume_symbols(self, limit: int) -> list:
        return list(self.symbols_data.keys())[:limit]
    
    async def get_orderbook(self, symbol: str, depth: int = 20) -> dict:
        if symbol not in self.symbols_data:
            return {"asks": [], "bids": []}
        return self.symbols_data[symbol]["orderbook"]
    
    async def get_current_price(self, symbol: str) -> float:
        if symbol not in self.symbols_data:
            return 0.0
        return self.symbols_data[symbol]["price"]
    
    async def get_volatility_data(self, symbol: str, timeframe: str) -> dict:
        return {"volatility": 0.025, "price_change": 0.015}
    
    # Реализуем недостающие абстрактные методы
    async def get_futures_pairs(self) -> list:
        return list(self.symbols_data.keys())
    
    async def get_24h_volume_stats(self, symbols: list = None) -> dict:
        return {symbol: {"volume": "1000000000"} for symbol in self.symbols_data.keys()}
    
    async def get_24h_ticker(self, symbol: str) -> dict:
        return {
            "volume": "10000",
            "quoteVolume": "10000000",
            "priceChange": "100.0",
            "priceChangePercent": "1.5"
        }


class TestPrimaryScanner:
    """Тесты первичного сканнера"""
    
    @pytest.fixture
    def mock_exchange(self):
        return MockExchange()
    
    @pytest.fixture
    def mock_observer_pool(self):
        pool = MagicMock()
        pool.add_order_from_primary_scan = MagicMock()
        return pool
    
    @pytest.fixture
    def scanner(self, mock_exchange, mock_observer_pool):
        return PrimaryScanner(mock_exchange, mock_observer_pool)
    
    @pytest.mark.asyncio
    async def test_получение_списка_торговых_пар(self, scanner):
        """Тест получения списка торговых пар"""
        # Получаем список символов
        symbols = await scanner.exchange.get_top_volume_symbols(250)
        
        # Проверяем что получили символы
        assert len(symbols) > 0
        assert "BTCUSDT" in symbols
        assert "ETHUSDT" in symbols
    
    @pytest.mark.asyncio
    async def test_фильтрация_стейблкоинов(self, scanner):
        """Тест исключения стейблкоинов"""
        from src.utils.helpers import filter_symbols
        
        # Список символов со стейблкоинами
        test_symbols = ["BTCUSDT", "ETHBUSD", "ADAUSDC", "DOTFDUSD", "LINKUSDT"]
        
        # Фильтруем
        filtered = filter_symbols(test_symbols)
        
        # Проверяем что стейблкоины исключены
        assert len(filtered) == 0  # Все символы заканчиваются на стейблкоины
        
        # Тестируем с обычными символами
        normal_symbols = ["BTCETH", "ADABNB", "LINKBTC"]
        filtered_normal = filter_symbols(normal_symbols)
        assert len(filtered_normal) == len(normal_symbols)
    
    @pytest.mark.asyncio 
    async def test_определение_больших_ордеров(self, scanner):
        """Тест критериев определения больших ордеров"""
        # Получаем orderbook
        orderbook = await scanner.exchange.get_orderbook("BTCUSDT", 20)
        current_price = await scanner.exchange.get_current_price("BTCUSDT")
        
        # Анализируем большие ордера в asks
        large_asks = scanner._find_large_orders_in_side_simple(
            "BTCUSDT", orderbook["asks"], current_price, "ASK", 0.025
        )
        
        # Проверяем что нашли большой ордер
        assert len(large_asks) > 0
        
        # Проверяем что большой ордер действительно большой
        large_order = large_asks[0]
        assert large_order.usd_value > large_order.average_order_size * 3.5
        
        # Проверяем структуру найденного ордера
        assert large_order.symbol == "BTCUSDT"
        assert large_order.order_type == "ASK"
        assert large_order.usd_value > 0
        assert large_order.distance_percent >= 0
        assert large_order.order_hash is not None
    
    @pytest.mark.asyncio
    async def test_генерация_хэшей(self, scanner):
        """Тест генерации уникальных хэшей для ордеров"""
        # Генерируем хэши для разных ордеров
        hash1 = scanner._generate_order_hash("BTCUSDT", 65000.0, 10.0, "ASK")
        hash2 = scanner._generate_order_hash("BTCUSDT", 65000.0, 10.0, "BID")
        hash3 = scanner._generate_order_hash("ETHUSDT", 3200.0, 5.0, "ASK")
        
        # Проверяем уникальность
        assert hash1 != hash2
        assert hash1 != hash3
        assert hash2 != hash3
        
        # Проверяем формат хэша
        assert "-" in hash1
        symbol_part, hash_part = hash1.split("-", 1)
        assert len(symbol_part) <= 6
        assert len(hash_part) == 12
    
    @pytest.mark.asyncio
    async def test_полное_сканирование(self, scanner):
        """Тест полного сканирования всех символов"""
        # Запускаем тестовое сканирование
        test_symbols = ["BTCUSDT", "ETHUSDT"]
        results = await scanner.run_test_scan(test_symbols)
        
        # Проверяем результаты
        assert results["scan_completed"] is True
        assert results["total_symbols_scanned"] == len(test_symbols)
        assert results["total_large_orders"] > 0
        assert results["duration_seconds"] > 0
        
        # Проверяем статистику
        assert "statistics" in results
        assert "categories" in results
        
        # Проверяем топ ордера
        assert "top_orders" in results
        assert len(results["top_orders"]) > 0
        
        # Проверяем что ордера отсортированы по размеру
        top_orders = results["top_orders"]
        for i in range(len(top_orders) - 1):
            assert top_orders[i]["usd_value"] >= top_orders[i + 1]["usd_value"]
    
    @pytest.mark.asyncio
    async def test_отправка_в_пул_наблюдателя(self, scanner):
        """Тест передачи найденных ордеров в пул наблюдателя"""
        # Запускаем сканирование
        await scanner.run_test_scan(["BTCUSDT"])
        
        # Проверяем что вызвался метод добавления ордера в пул наблюдателя
        assert scanner.observer_pool.add_order_from_primary_scan.called
        
        # Проверяем переданные данные
        call_args = scanner.observer_pool.add_order_from_primary_scan.call_args_list
        assert len(call_args) > 0
        
        # Проверяем структуру переданного ордера
        order_data = call_args[0][0][0]
        required_fields = [
            "symbol", "price", "quantity", "type", "usd_value", 
            "distance_percent", "size_vs_average", "first_seen", "order_hash"
        ]
        
        for field in required_fields:
            assert field in order_data
    
    @pytest.mark.asyncio
    async def test_работа_с_пустыми_стаканами(self, scanner):
        """Тест обработки пустых стаканов"""
        # Создаем мок с пустыми стаканами
        empty_orderbook = {"asks": [], "bids": []}
        
        with patch.object(scanner.exchange, 'get_orderbook', return_value=empty_orderbook):
            results = await scanner.run_test_scan(["EMPTYSYMBOL"])
        
        # Проверяем что сканирование завершилось без ошибок
        assert results["scan_completed"] is True
        assert results["total_large_orders"] == 0
    
    @pytest.mark.asyncio
    async def test_обработка_ошибок_api(self, scanner):
        """Тест обработки ошибок API"""
        # Создаем мок который выбрасывает исключение
        with patch.object(scanner.exchange, 'get_orderbook', side_effect=Exception("API Error")):
            # Сканирование должно завершиться без исключений
            results = await scanner.run_test_scan(["ERRORSYMBOL"])
            
            # Проверяем что сканирование завершилось
            assert results["scan_completed"] is True
    
    @pytest.mark.asyncio
    async def test_определение_круглых_уровней(self, scanner):
        """Тест определения психологических уровней"""
        # Тестируем круглые цены
        assert scanner._is_near_round_level(1.0000) is True
        assert scanner._is_near_round_level(0.5000) is True  
        assert scanner._is_near_round_level(100.0) is True
        assert scanner._is_near_round_level(0.01000) is True
        
        # Тестируем не круглые цены
        assert scanner._is_near_round_level(1.2345) is False
        assert scanner._is_near_round_level(67.834) is False
        
        # Тестируем близкие к круглым (в пределах 2%)
        assert scanner._is_near_round_level(0.9980) is True  # Близко к 1.0
        assert scanner._is_near_round_level(1.0195) is True  # Близко к 1.0
    
    def test_валидация_конфигурации(self, scanner):
        """Тест валидации конфигурации сканнера"""
        config = scanner.config
        
        # Проверяем наличие обязательных параметров
        required_params = [
            "workers_count", "top_coins_limit", "large_order_multiplier",
            "orderbook_depth", "excluded_suffixes", "api_timeout"
        ]
        
        for param in required_params:
            assert param in config, f"Отсутствует параметр конфигурации: {param}"
        
        # Проверяем значения параметров
        assert config["workers_count"] > 0
        assert config["top_coins_limit"] > 0  
        assert config["large_order_multiplier"] > 1.0
        assert config["orderbook_depth"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
