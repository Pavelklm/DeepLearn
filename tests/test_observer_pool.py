"""
Тест пула наблюдателя
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta

from src.pools.observer_pool import ObserverPool
from src.pools.hot_pool import HotPool
from src.exchanges.base_exchange import BaseExchange


class MockExchange(BaseExchange):
    """Мок биржи для тестирования"""
    
    def __init__(self):
        super().__init__("test", {})
        self.orderbook_responses = {}
        self.price_responses = {}
    
    async def connect(self) -> bool:
        """Реализация абстрактного метода connect"""
        self.is_connected = True
        return True
    
    async def disconnect(self):
        """Реализация абстрактного метода disconnect"""
        self.is_connected = False
    
    def set_orderbook_response(self, symbol: str, orderbook: dict):
        self.orderbook_responses[symbol] = orderbook
    
    def set_price_response(self, symbol: str, price: float):
        self.price_responses[symbol] = price
    
    async def get_orderbook(self, symbol: str, depth: int = 20) -> dict:
        return self.orderbook_responses.get(symbol, {"asks": [], "bids": []})
    
    async def get_current_price(self, symbol: str) -> float:
        return self.price_responses.get(symbol, 1000.0)
    
    async def get_volatility_data(self, symbol: str, timeframe: str) -> dict:
        return {"volatility": 0.02, "price_change": 0.01}
    
    # Реализуем недостающие абстрактные методы
    async def get_futures_pairs(self) -> list:
        return ["BTCUSDT", "ETHUSDT", "ADAUSDT"]
    
    async def get_24h_volume_stats(self, symbols: list = None) -> dict:
        return {"BTCUSDT": {"volume": "2000000000"}, "ETHUSDT": {"volume": "1500000000"}, "ADAUSDT": {"volume": "500000000"}}
    
    async def get_top_volume_symbols(self, limit: int) -> list:
        return ["BTCUSDT", "ETHUSDT", "ADAUSDT"][:limit]
    
    async def get_24h_ticker(self, symbol: str) -> dict:
        return {
            "volume": "10000",
            "quoteVolume": "10000000",
            "priceChange": "100.0",
            "priceChangePercent": "1.5"
        }


class TestObserverPool:
    """Тесты пула наблюдателя"""
    
    @pytest.fixture
    def mock_exchange(self):
        return MockExchange()
    
    @pytest.fixture  
    def mock_hot_pool(self):
        pool = MagicMock()
        pool.add_order_from_observer = MagicMock()
        return pool
    
    @pytest.fixture
    def observer_pool(self, mock_exchange, mock_hot_pool):
        pool = ObserverPool(mock_exchange)
        pool.hot_pool = mock_hot_pool
        return pool
    
    def test_добавление_ордера_от_первичного_сканера(self, observer_pool):
        """Тест добавления ордера от первичного сканнера"""
        order_data = {
            "symbol": "BTCUSDT",
            "price": 65000.0,
            "quantity": 10.0,
            "type": "ASK",
            "usd_value": 650000.0,
            "distance_percent": 1.5,
            "size_vs_average": 5.0,
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "order_hash": "BTCUSD-test123"
        }
        
        # Добавляем ордер
        observer_pool.add_order_from_primary_scan(order_data)
        
        # Проверяем что ордер добавлен
        assert "BTCUSDT" in observer_pool.observed_symbols
        assert len(observer_pool.observed_symbols["BTCUSDT"]) == 1
        
        # Проверяем данные ордера
        tracked_order = observer_pool.observed_symbols["BTCUSDT"][0]
        assert tracked_order["symbol"] == "BTCUSDT"
        assert tracked_order["order_hash"] == "BTCUSD-test123"
        assert tracked_order["first_seen"] is not None
    
    @pytest.mark.asyncio
    async def test_определение_того_же_ордера(self, observer_pool, mock_exchange):
        """Тест логики определения 'того же' ордера"""
        # Настраиваем мок биржи
        mock_exchange.set_orderbook_response("BTCUSDT", {
            "asks": [["65000.0", "8.0"]],  # Та же цена, уменьшение < 70%
            "bids": []
        })
        mock_exchange.set_price_response("BTCUSDT", 64500.0)
        
        # Добавляем исходный ордер
        original_order = {
            "symbol": "BTCUSDT",
            "price": 65000.0,
            "quantity": 10.0,
            "type": "ASK",
            "usd_value": 650000.0,
            "order_hash": "BTCUSD-test123",
            "first_seen": datetime.now(timezone.utc).isoformat()
        }
        
        observer_pool.add_order_from_primary_scan(original_order)
        
        # Проверяем обновление того же ордера
        await observer_pool._scan_symbol("BTCUSDT")
        
        # Ордер должен остаться (та же цена, потеря < 70%)
        assert "BTCUSDT" in observer_pool.observed_symbols
        assert len(observer_pool.observed_symbols["BTCUSDT"]) == 1
    
    @pytest.mark.asyncio
    async def test_смерть_ордера_потеря_объема(self, observer_pool, mock_exchange):
        """Тест смерти ордера при потере > 70% объема"""
        # Настраиваем мок: та же цена, но потеря > 70%
        mock_exchange.set_orderbook_response("BTCUSDT", {
            "asks": [["65000.0", "2.0"]],  # Потеря > 70% (было 10, стало 2)
            "bids": []
        })
        mock_exchange.set_price_response("BTCUSDT", 64500.0)
        
        # Добавляем ордер
        order_data = {
            "symbol": "BTCUSDT",
            "price": 65000.0,
            "quantity": 10.0,
            "type": "ASK",
            "usd_value": 650000.0,
            "order_hash": "BTCUSD-test123",
            "first_seen": datetime.now(timezone.utc).isoformat()
        }
        
        observer_pool.add_order_from_primary_scan(order_data)
        
        # Сканируем
        await observer_pool._scan_symbol("BTCUSDT")
        
        # Ордер должен "умереть"
        tracked_order = observer_pool.observed_symbols["BTCUSDT"][0]
        assert tracked_order["is_alive"] is False
    
    @pytest.mark.asyncio
    async def test_смерть_ордера_изменение_цены(self, observer_pool, mock_exchange):
        """Тест смерти ордера при изменении цены"""
        # Настраиваем мок: другая цена
        mock_exchange.set_orderbook_response("BTCUSDT", {
            "asks": [["65100.0", "10.0"]],  # Цена изменилась
            "bids": []
        })
        mock_exchange.set_price_response("BTCUSDT", 64500.0)
        
        # Добавляем ордер
        order_data = {
            "symbol": "BTCUSDT",
            "price": 65000.0,  # Исходная цена
            "quantity": 10.0,
            "type": "ASK",
            "usd_value": 650000.0,
            "order_hash": "BTCUSD-test123",
            "first_seen": datetime.now(timezone.utc).isoformat()
        }
        
        observer_pool.add_order_from_primary_scan(order_data)
        
        # Сканируем
        await observer_pool._scan_symbol("BTCUSDT")
        
        # Старый ордер должен "умереть", создастся новый
        orders = observer_pool.observed_symbols["BTCUSDT"]
        assert len([o for o in orders if o["is_alive"]]) >= 1  # Новый ордер
        assert len([o for o in orders if not o["is_alive"]]) >= 1  # Мертвый ордер
    
    @pytest.mark.asyncio  
    async def test_воскрешение_ордера(self, observer_pool, mock_exchange):
        """Тест воскрешения ордера с новым хэшем"""
        # Сначала ордер исчезает
        mock_exchange.set_orderbook_response("BTCUSDT", {
            "asks": [],  # Ордер исчез
            "bids": []
        })
        mock_exchange.set_price_response("BTCUSDT", 64500.0)
        
        # Добавляем ордер
        order_data = {
            "symbol": "BTCUSDT",
            "price": 65000.0,
            "quantity": 10.0,
            "type": "ASK",
            "usd_value": 650000.0,
            "order_hash": "BTCUSD-test123",
            "first_seen": datetime.now(timezone.utc).isoformat()
        }
        
        observer_pool.add_order_from_primary_scan(order_data)
        
        # Сканируем - ордер исчезает
        await observer_pool._scan_symbol("BTCUSDT")
        
        # Затем ордер появляется снова
        mock_exchange.set_orderbook_response("BTCUSDT", {
            "asks": [["65000.0", "10.0"]],  # Ордер вернулся
            "bids": []
        })
        
        # Сканируем снова  
        await observer_pool._scan_symbol("BTCUSDT")
        
        # Должен быть создан новый ордер с новым хэшем
        alive_orders = [o for o in observer_pool.observed_symbols["BTCUSDT"] if o["is_alive"]]
        assert len(alive_orders) == 1
        assert alive_orders[0]["order_hash"] != "BTCUSD-test123"  # Новый хэш
    
    @pytest.mark.asyncio
    async def test_переход_в_горячий_пул(self, observer_pool, mock_exchange, mock_hot_pool):
        """Тест перехода ордера в горячий пул после 1 минуты"""
        # Настраиваем мок
        mock_exchange.set_orderbook_response("BTCUSDT", {
            "asks": [["65000.0", "10.0"]],
            "bids": []
        })
        mock_exchange.set_price_response("BTCUSDT", 64500.0)
        
        # Добавляем ордер с временем > 60 секунд назад
        old_time = datetime.now(timezone.utc) - timedelta(seconds=70)
        order_data = {
            "symbol": "BTCUSDT",
            "price": 65000.0,
            "quantity": 10.0,
            "type": "ASK",
            "usd_value": 650000.0,
            "order_hash": "BTCUSD-test123",
            "first_seen": old_time.isoformat()
        }
        
        observer_pool.add_order_from_primary_scan(order_data)
        
        # Обновляем время создания в отслеживаемом ордере
        observer_pool.observed_symbols["BTCUSDT"][0]["first_seen"] = old_time
        
        # Сканируем
        await observer_pool._scan_symbol("BTCUSDT")
        
        # Проверяем что ордер был передан в горячий пул
        assert mock_hot_pool.add_order_from_observer.called
        
        # Проверяем что ордер помечен как переданный
        tracked_order = observer_pool.observed_symbols["BTCUSDT"][0]
        assert tracked_order.get("moved_to_hot_pool") is True
    
    @pytest.mark.asyncio
    async def test_возврат_монеты_в_общий_пул(self, observer_pool):
        """Тест возврата монеты в общий пул когда все ордера исчезли"""
        # Добавляем ордер
        order_data = {
            "symbol": "BTCUSDT",
            "price": 65000.0,
            "quantity": 10.0,
            "type": "ASK",
            "usd_value": 650000.0,
            "order_hash": "BTCUSD-test123",
            "first_seen": datetime.now(timezone.utc).isoformat()
        }
        
        observer_pool.add_order_from_primary_scan(order_data)
        
        # Помечаем ордер как мертвый
        observer_pool.observed_symbols["BTCUSDT"][0]["is_alive"] = False
        
        # Выполняем 11 пустых сканов (больше cleanup_scans из конфига)
        for _ in range(11):
            await observer_pool._cleanup_empty_symbols()
        
        # Монета должна быть удалена из наблюдения
        assert "BTCUSDT" not in observer_pool.observed_symbols
    
    @pytest.mark.asyncio
    async def test_адаптивное_количество_воркеров(self, observer_pool):
        """Тест адаптивного изменения количества воркеров"""
        # Изначально нет символов - должен быть 1 воркер
        workers_needed = observer_pool._calculate_workers_needed()
        assert workers_needed == 1  # Минимум 1 воркер
        
        # Добавляем символы
        for i in range(7):
            order_data = {
                "symbol": f"SYMBOL{i}USDT",
                "price": 1000.0,
                "quantity": 10.0,
                "type": "ASK",
                "usd_value": 10000.0,
                "order_hash": f"SYM{i}-test123",
                "first_seen": datetime.now(timezone.utc).isoformat()
            }
            observer_pool.add_order_from_primary_scan(order_data)
        
        # Теперь должно быть больше воркеров
        workers_needed = observer_pool._calculate_workers_needed()
        assert workers_needed > 1
    
    def test_получение_статистики(self, observer_pool):
        """Тест получения статистики пула наблюдателя"""
        # Добавляем тестовые ордера
        for i in range(3):
            order_data = {
                "symbol": f"SYMBOL{i}USDT",
                "price": 1000.0 + i,
                "quantity": 10.0,
                "type": "ASK",
                "usd_value": 10000.0 + i,
                "order_hash": f"SYM{i}-test123",
                "first_seen": datetime.now(timezone.utc).isoformat()
            }
            observer_pool.add_order_from_primary_scan(order_data)
        
        # Помечаем один ордер как мертвый
        observer_pool.observed_symbols["SYMBOL1USDT"][0]["is_alive"] = False
        
        # Получаем статистику
        stats = observer_pool.get_stats()
        
        # Проверяем статистику
        assert stats["total_symbols"] == 3
        assert stats["total_orders"] == 3
        assert stats["alive_orders"] == 2
        assert stats["dead_orders"] == 1
        assert "active_symbols" in stats
    
    @pytest.mark.asyncio
    async def test_обработка_ошибок_сканирования(self, observer_pool, mock_exchange):
        """Тест обработки ошибок при сканировании"""
        # Настраиваем мок чтобы выбрасывать исключение
        with patch.object(mock_exchange, 'get_orderbook', side_effect=Exception("API Error")):
            
            # Добавляем ордер
            order_data = {
                "symbol": "BTCUSDT",
                "price": 65000.0,
                "quantity": 10.0,
                "type": "ASK",
                "usd_value": 650000.0,
                "order_hash": "BTCUSD-test123",
                "first_seen": datetime.now(timezone.utc).isoformat()
            }
            
            observer_pool.add_order_from_primary_scan(order_data)
            
            # Сканирование должно завершиться без исключений
            await observer_pool._scan_symbol("BTCUSDT")
            
            # Ордер должен остаться в системе (не быть удаленным из-за ошибки)
            assert "BTCUSDT" in observer_pool.observed_symbols
    
    def test_валидация_данных_ордера(self, observer_pool):
        """Тест валидации входящих данных ордера"""
        # Корректные данные
        valid_order = {
            "symbol": "BTCUSDT",
            "price": 65000.0,
            "quantity": 10.0,
            "type": "ASK",
            "usd_value": 650000.0,
            "order_hash": "BTCUSD-test123",
            "first_seen": datetime.now(timezone.utc).isoformat()
        }
        
        observer_pool.add_order_from_primary_scan(valid_order)
        assert "BTCUSDT" in observer_pool.observed_symbols
        
        # Некорректные данные - отсутствует обязательное поле
        invalid_order = {
            "symbol": "ETHUSDT",
            "price": 3200.0,
            # quantity отсутствует
            "type": "ASK",
            "usd_value": 32000.0,
            "order_hash": "ETHUSD-test456",
            "first_seen": datetime.now(timezone.utc).isoformat()
        }
        
        # Должна быть обработана ошибка валидации
        observer_pool.add_order_from_primary_scan(invalid_order)
        # Некорректный ордер не должен быть добавлен или должен быть добавлен с дефолтными значениями


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
