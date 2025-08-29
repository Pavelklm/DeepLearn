"""
Тест горячего пула
"""

import pytest
import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta
from pathlib import Path

from src.pools.hot_pool import HotPool
from src.exchanges.base_exchange import BaseExchange
from src.analytics.weight_calculator import WeightCalculator


class MockExchange(BaseExchange):
    """Мок биржи для тестирования"""
    
    def __init__(self):
        super().__init__("test", {})
        self.price_responses = {}
        self.volatility_responses = {}
    
    async def connect(self) -> bool:
        self.is_connected = True
        return True
    
    async def disconnect(self):
        self.is_connected = False
    
    def set_price_response(self, symbol: str, price: float):
        self.price_responses[symbol] = price
    
    def set_volatility_response(self, symbol: str, volatility: float):
        self.volatility_responses[symbol] = {"volatility": volatility, "price_change": 0.01}
    
    async def get_current_price(self, symbol: str) -> float:
        return self.price_responses.get(symbol, 1000.0)
    
    async def get_volatility_data(self, symbol: str, timeframe: str) -> dict:
        return self.volatility_responses.get(symbol, {"volatility": 0.02, "price_change": 0.01})
    
    async def get_orderbook(self, symbol: str, depth: int = 20) -> dict:
        return {
            "asks": [["1000.0", "10.0"], ["1001.0", "15.0"]],
            "bids": [["999.0", "12.0"], ["998.0", "8.0"]]
        }
    
    # Реализуем недостающие абстрактные методы
    async def get_futures_pairs(self) -> list:
        return ["BTCUSDT", "ETHUSDT", "ADAUSDT"]
    
    async def get_24h_volume_stats(self, symbols: list = None) -> dict:
        return {"BTCUSDT": {"volume": "2000000000"}, "ETHUSDT": {"volume": "1500000000"}}
    
    async def get_top_volume_symbols(self, limit: int) -> list:
        return ["BTCUSDT", "ETHUSDT", "ADAUSDT"][:limit]
    
    async def get_24h_ticker(self, symbol: str) -> dict:
        return {
            "volume": "10000",
            "quoteVolume": "10000000",
            "priceChange": "100.0",
            "priceChangePercent": "1.5"
        }


class MockTrackedOrder:
    """Мок отслеживаемого ордера из Observer Pool"""
    def __init__(self, order_hash, symbol="BTCUSDT", price=65000.0, quantity=10.0, 
                 side="ASK", usd_value=650000.0):
        self.order_hash = order_hash
        self.symbol = symbol
        self.price = price
        self.quantity = quantity
        self.side = side
        self.usd_value = usd_value
        self.first_seen = datetime.now(timezone.utc) - timedelta(seconds=90)
        self.last_seen = datetime.now(timezone.utc)
        self.scan_count = 5


class TestHotPool:
    """Тесты горячего пула"""
    
    @pytest.fixture
    def mock_exchange(self):
        exchange = MockExchange()
        exchange.set_price_response("BTCUSDT", 65000.0)
        exchange.set_price_response("ETHUSDT", 3200.0)
        exchange.set_volatility_response("BTCUSDT", 0.025)
        exchange.set_volatility_response("ETHUSDT", 0.030)
        return exchange
    
    @pytest.fixture
    def mock_websocket_server(self):
        server = MagicMock()
        server.broadcast_hot_pool_update = AsyncMock()
        server.send_hot_pool_data = AsyncMock()
        server.is_running = True
        return server
    
    @pytest.fixture
    def hot_pool(self, mock_exchange, mock_websocket_server):
        pool = HotPool(mock_exchange)
        pool.websocket_server = mock_websocket_server
        return pool
    
    @pytest.fixture
    def sample_tracked_order(self):
        """Образец отслеживаемого ордера от пула наблюдателя"""
        return MockTrackedOrder(
            order_hash="BTCUSD-abc123456",
            symbol="BTCUSDT",
            price=65500.0,
            quantity=10.0,
            side="ASK",
            usd_value=655000.0
        )
    
    @pytest.fixture
    def sample_update_data(self):
        """Образец данных обновления"""
        return {
            "lifetime_seconds": 90.0,
            "scan_count": 5,
            "volatility_1h": 0.025
        }
    
    @pytest.mark.asyncio
    async def test_добавление_ордера_от_наблюдателя(self, hot_pool, sample_tracked_order, sample_update_data):
        """Тест добавления ордера от пула наблюдателя"""
        # Добавляем ордер с правильными параметрами
        await hot_pool.add_order_from_observer(sample_tracked_order, sample_update_data)
        
        # Проверяем что ордер добавлен
        assert sample_tracked_order.order_hash in hot_pool.hot_orders
        
        # Проверяем структуру добавленного ордера
        hot_order = hot_pool.hot_orders[sample_tracked_order.order_hash]
        assert hot_order.symbol == "BTCUSDT"
        assert hot_order.order_hash == "BTCUSD-abc123456"
        assert hot_order.exchange == "test"
        assert hot_order.usd_value == 655000.0
    
    @pytest.mark.asyncio
    async def test_получение_ордеров_символа(self, hot_pool, sample_tracked_order, sample_update_data):
        """Тест получения ордеров для конкретного символа"""
        # Добавляем ордер
        await hot_pool.add_order_from_observer(sample_tracked_order, sample_update_data)
        
        # Получаем ордера для символа
        symbol_orders = hot_pool.get_symbol_orders("BTCUSDT")
        
        assert len(symbol_orders) == 1
        assert symbol_orders[0].symbol == "BTCUSDT"
        assert symbol_orders[0].order_hash == sample_tracked_order.order_hash
    
    @pytest.mark.asyncio
    async def test_удаление_ордера(self, hot_pool, sample_tracked_order, sample_update_data):
        """Тест удаления ордера из горячего пула"""
        # Добавляем ордер
        await hot_pool.add_order_from_observer(sample_tracked_order, sample_update_data)
        
        # Проверяем что добавился
        assert sample_tracked_order.order_hash in hot_pool.hot_orders
        
        # Удаляем ордер
        hot_pool._remove_hot_order(sample_tracked_order.order_hash)
        
        # Проверяем что удалился
        assert sample_tracked_order.order_hash not in hot_pool.hot_orders
        assert len(hot_pool.get_symbol_orders("BTCUSDT")) == 0
    
    @pytest.mark.asyncio
    async def test_обновление_ордера(self, hot_pool, sample_tracked_order, sample_update_data):
        """Тест обновления параметров ордера"""
        # Добавляем ордер
        await hot_pool.add_order_from_observer(sample_tracked_order, sample_update_data)
        
        # Подготавливаем обновления
        updates = {
            "current_price": 66000.0,
            "quantity": 8.0,
            "usd_value": 528000.0,
            "lifetime_seconds": 150.0,
            "stability_score": 0.8
        }
        
        # Обновляем ордер
        await hot_pool._update_hot_order(sample_tracked_order.order_hash, updates)
        
        # Проверяем обновления
        hot_order = hot_pool.hot_orders[sample_tracked_order.order_hash]
        assert hot_order.current_price == 66000.0
        assert hot_order.quantity == 8.0
        assert hot_order.usd_value == 528000.0
        assert hot_order.stability_score == 0.8
    
    def test_получение_статистики_пула(self, hot_pool):
        """Тест получения статистики горячего пула"""
        # Получаем статистику пустого пула
        stats = hot_pool.get_stats()
        
        # Проверяем структуру статистики
        required_stats = [
            "is_running", "total_orders", "active_symbols", 
            "categories", "worker_stats"
        ]
        
        for stat in required_stats:
            assert stat in stats, f"Отсутствует статистика: {stat}"
        
        # Проверяем начальные значения
        assert stats["total_orders"] == 0
        assert stats["active_symbols"] == 0
        assert isinstance(stats["categories"], dict)
        assert "basic" in stats["categories"]
        assert "gold" in stats["categories"]
        assert "diamond" in stats["categories"]
    
    @pytest.mark.asyncio
    async def test_статистика_с_ордерами(self, hot_pool, sample_update_data):
        """Тест статистики с добавленными ордерами"""
        # Добавляем несколько тестовых ордеров
        for i in range(3):
            tracked_order = MockTrackedOrder(
                order_hash=f"TEST{i}-abc123",
                symbol=f"SYMBOL{i}USDT",
                usd_value=100000.0 * (i + 1)
            )
            await hot_pool.add_order_from_observer(tracked_order, sample_update_data)
        
        # Получаем статистику
        stats = hot_pool.get_stats()
        
        # Проверяем значения
        assert stats["total_orders"] == 3
        assert stats["active_symbols"] == 3
        assert "avg_lifetime" in stats
        assert stats["avg_lifetime"] > 0
    
    @pytest.mark.asyncio
    async def test_сохранение_в_файл(self, hot_pool, sample_tracked_order, sample_update_data):
        """Тест сохранения данных в файл"""
        # Добавляем ордер
        await hot_pool.add_order_from_observer(sample_tracked_order, sample_update_data)
        
        # Сохраняем в файл
        await hot_pool._save_to_file()
        
        # Проверяем что файл создался
        assert hot_pool.output_file.exists()
        
        # Проверяем содержимое файла
        with open(hot_pool.output_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        assert "timestamp" in data
        assert "total_orders" in data
        assert "orders" in data
        assert data["total_orders"] == 1
        assert len(data["orders"]) == 1
        
        # Проверяем структуру ордера в файле
        order_data = data["orders"][0]
        assert order_data["symbol"] == "BTCUSDT"
        assert order_data["order_hash"] == "BTCUSD-abc123456"
        assert order_data["usd_value"] == 655000.0
    
    @pytest.mark.asyncio
    async def test_websocket_трансляция(self, hot_pool, sample_tracked_order, sample_update_data, mock_websocket_server):
        """Тест трансляции через WebSocket"""
        # Добавляем ордер
        await hot_pool.add_order_from_observer(sample_tracked_order, sample_update_data)
        
        # Вызываем трансляцию
        await hot_pool._broadcast_hot_pool_update()
        
        # Проверяем что WebSocket метод был вызван
        assert mock_websocket_server.send_hot_pool_data.called
        
        # Проверяем переданные данные
        call_args = mock_websocket_server.send_hot_pool_data.call_args[0][0]
        assert call_args["total_orders"] == 1
        assert call_args["exchange"] == "test"
        assert len(call_args["orders"]) == 1
        assert call_args["orders"][0]["symbol"] == "BTCUSDT"
    
    @pytest.mark.asyncio
    async def test_управление_воркерами(self, hot_pool, sample_update_data):
        """Тест управления воркерами через AdaptiveWorkerManager"""
        # Проверяем что worker_manager существует
        assert hasattr(hot_pool, 'worker_manager')
        assert hot_pool.worker_manager is not None
        
        # Добавляем несколько ордеров для разных символов
        for i in range(5):
            tracked_order = MockTrackedOrder(
                order_hash=f"WORKER{i}-test",
                symbol=f"SYMBOL{i}USDT"
            )
            await hot_pool.add_order_from_observer(tracked_order, sample_update_data)
        
        # Проверяем что символы добавились
        assert len(hot_pool.symbol_orders) == 5
        
        # Получаем статистику воркеров
        worker_stats = hot_pool.worker_manager.get_all_stats()
        assert "manager_stats" in worker_stats
        assert "workers" in worker_stats
    
    @pytest.mark.asyncio
    async def test_обработка_обновлений_воркеров(self, hot_pool, sample_tracked_order, sample_update_data):
        """Тест обработки обновлений от воркеров"""
        # Добавляем ордер
        await hot_pool.add_order_from_observer(sample_tracked_order, sample_update_data)
        
        # Симулируем результат сканирования от воркера
        scan_result = {
            "symbol": "BTCUSDT",
            "current_price": 66000.0,
            "updates": [
                {
                    "type": "order_updated",
                    "order_hash": sample_tracked_order.order_hash,
                    "updates": {
                        "current_price": 66000.0,
                        "quantity": 8.0,
                        "usd_value": 528000.0,
                        "stability_score": 0.9
                    },
                    "significant_change": True
                }
            ]
        }
        
        # Обрабатываем обновления
        await hot_pool.handle_updates(scan_result)
        
        # Проверяем что ордер обновился
        hot_order = hot_pool.hot_orders[sample_tracked_order.order_hash]
        assert hot_order.current_price == 66000.0
        assert hot_order.quantity == 8.0
        assert hot_order.stability_score == 0.9


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
