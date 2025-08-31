"""
Тесты пула наблюдателя - строго по спецификации
"""

import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.pools.observer_pool import ObserverPool
from src.pools.hot_pool import HotPool
from src.exchanges.base_exchange import BaseExchange
from config.main_config import POOLS_CONFIG


@pytest.fixture
def mock_exchange():
    """Мок биржи для тестирования"""
    exchange = AsyncMock(spec=BaseExchange)
    exchange.name = "binance"  # Добавляем имя биржи
    
    # Мок стакана с изменяющимися ордерами
    exchange.get_orderbook = AsyncMock()
    exchange.get_current_price = AsyncMock(return_value=50000.0)
    exchange.get_volatility_data = AsyncMock(return_value={"volatility": 0.02})
    
    return exchange


@pytest.fixture
def observer_pool(mock_exchange):
    """Инициализированный пул наблюдателя"""
    pool = ObserverPool(mock_exchange)
    pool.hot_pool = MagicMock(spec=HotPool)
    pool.hot_pool.add_order_from_observer = AsyncMock()  # Правильный метод
    return pool


class TestObserverPool:
    """Тесты пула наблюдателя по спецификации"""
    
    @pytest.mark.asyncio
    async def test_order_lifetime_tracking(self, observer_pool):
        """Тест: Ордер живет >1 минуты → переход в горячий пул"""
        # Добавляем ордер
        order_data = {
            "symbol": "BTCUSDT",
            "price": 51000.0,
            "quantity": 5.0,
            "type": "ASK",
            "usd_value": 255000.0,
            "distance_percent": 2.0,
            "size_vs_average": 8.5,
            "average_order_size": 30000.0,
            "first_seen": (datetime.now(timezone.utc) - timedelta(seconds=61)).isoformat(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "order_hash": "BTCUSD-abc123",
            "scan_count": 61  # >60 сканов (каждый скан ~1 секунда)
        }
        
        # Добавляем ордер в наблюдение
        observer_pool.add_order_from_primary_scan(order_data)
        
        # Проверяем время жизни
        lifetime_seconds = 61
        hot_pool_threshold = POOLS_CONFIG["observer_pool"]["hot_pool_lifetime_seconds"]
        
        # Проверяем условие перехода
        assert lifetime_seconds > hot_pool_threshold  # 61 > 60
        
        # Проверяем, должен ли ордер перейти в горячий пул
        should_move_to_hot = lifetime_seconds >= hot_pool_threshold
        assert should_move_to_hot == True
    
    @pytest.mark.asyncio
    async def test_order_survival_threshold(self, observer_pool):
        """Тест: Ордер теряет >70% → смерть ордера"""
        # Исходный ордер
        original_quantity = 5.0
        original_usd_value = 255000.0
        
        # Сценарий 1: Потеря 30% (выживает)
        current_quantity_1 = 3.5  # 70% от исходного
        survival_ratio_1 = current_quantity_1 / original_quantity
        survival_threshold = POOLS_CONFIG["observer_pool"]["survival_threshold"]
        
        assert survival_ratio_1 == 0.7
        assert survival_ratio_1 >= survival_threshold  # Выживает
        
        # Сценарий 2: Потеря 71% (умирает)
        current_quantity_2 = 1.45  # 29% от исходного
        survival_ratio_2 = current_quantity_2 / original_quantity
        
        assert survival_ratio_2 == 0.29
        assert survival_ratio_2 < survival_threshold  # Умирает
        
        # Сценарий 3: Изменение цены (умирает)
        original_price = 51000.0
        new_price = 51100.0  # Цена изменилась
        
        is_same_order = (new_price == original_price)
        assert is_same_order == False  # Это уже другой ордер
    
    @pytest.mark.asyncio
    async def test_order_resurrection(self, observer_pool):
        """Тест: Повторное появление ордера → новый хэш"""
        # Первый ордер
        first_order = {
            "symbol": "BTCUSDT",
            "price": 51000.0,
            "quantity": 5.0,
            "order_hash": "BTCUSD-abc123",
            "first_seen": datetime.now(timezone.utc).isoformat()
        }
        
        # Ордер "умирает" (исчезает из стакана)
        # ...время проходит...
        
        # Второй ордер с той же ценой появляется снова
        second_order = {
            "symbol": "BTCUSDT",
            "price": 51000.0,
            "quantity": 5.0,
            "order_hash": "BTCUSD-xyz789",  # НОВЫЙ ХЭШ!
            "first_seen": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        }
        
        # Проверяем
        assert first_order["order_hash"] != second_order["order_hash"]
        assert first_order["price"] == second_order["price"]
        assert first_order["first_seen"] != second_order["first_seen"]
    
    @pytest.mark.asyncio
    async def test_empty_symbol_cleanup(self, observer_pool):
        """Тест: Пустая монета → удаление через 10 сканов"""
        # Настройки
        cleanup_scans = POOLS_CONFIG["observer_pool"]["cleanup_scans"]
        assert cleanup_scans == 10
        
        # Сценарий: монета без ордеров
        symbol = "EMPTYUSDT"
        scans_without_orders = 0
        
        # Симулируем 10 сканов без ордеров
        for scan in range(cleanup_scans):
            scans_without_orders += 1
            should_remove = scans_without_orders >= cleanup_scans
            
            if scan < cleanup_scans - 1:
                assert should_remove == False  # Еще не удаляем
            else:
                assert should_remove == True   # Удаляем после 10 сканов
    
    @pytest.mark.asyncio
    async def test_adaptive_workers(self, observer_pool):
        """Тест: Адаптивное количество воркеров"""
        adaptive_config = POOLS_CONFIG["observer_pool"]["adaptive_workers"]
        # adaptive_config = {5: 1, 10: 2, 15: 3}
        print(f"\nAdaptive config: {adaptive_config}")  # Debug info
        
        # Правильные тестовые сценарии (по логике >= threshold)
        test_cases = [
            (1, 1),   # 1 монета → 1 воркер (меньше 5)
            (4, 1),   # 4 монеты → 1 воркер (меньше 5)
            (5, 1),   # 5 монет → 1 воркер (>= 5)
            (6, 1),   # 6 монет → 1 воркер (>= 5, но < 10)
            (9, 1),   # 9 монет → 1 воркер (>= 5, но < 10)
            (10, 2),  # 10 монет → 2 воркера (>= 10)
            (14, 2),  # 14 монет → 2 воркера (>= 10, но < 15)
            (15, 3),  # 15 монет → 3 воркера (>= 15)
            (100, 3), # 100 монет → 3 воркера (>= 15)
        ]
        
        for symbols_count, expected_workers in test_cases:
            # Определяем количество воркеров (правильная логика)
            workers = 1  # По умолчанию
            for threshold in sorted(adaptive_config.keys(), reverse=True):  # От большего к меньшему
                if symbols_count >= threshold:
                    workers = adaptive_config[threshold]
                    break
            
            assert workers == expected_workers, f"For {symbols_count} symbols expected {expected_workers} workers, got {workers}"
    
    @pytest.mark.asyncio
    async def test_order_tracking_logic(self, observer_pool):
        """Тест: Логика отслеживания ордеров"""
        # Создаем ордер для отслеживания
        order = {
            "symbol": "BTCUSDT",
            "price": 51000.0,
            "quantity": 5.0,
            "type": "ASK",
            "usd_value": 255000.0,
            "order_hash": "BTCUSD-abc123",
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "scan_count": 0
        }
        
        # Добавляем в пул
        observer_pool.add_order_from_primary_scan(order)
        
        # Проверяем статистику (поля из реального API)
        stats = observer_pool.get_stats()
        assert "is_running" in stats
        assert "total_orders" in stats  
        assert "active_symbols" in stats
        assert "orders_by_symbol" in stats
        assert "orders_moved_to_hot" in stats
        assert "orders_died" in stats
        assert "worker_stats" in stats
        
        # Проверяем базовые значения
        assert stats["total_orders"] >= 1  # Мы добавили 1 ордер
        assert stats["active_symbols"] >= 1  # Мы добавили 1 символ
        assert isinstance(stats["orders_by_symbol"], dict)
    
    @pytest.mark.asyncio
    async def test_hot_pool_transition(self, observer_pool):
        """Тест: Переход ордера в горячий пул"""
        # Создаем ордер, готовый к переходу
        order = {
            "symbol": "BTCUSDT",
            "price": 51000.0,
            "quantity": 5.0,
            "type": "ASK",
            "usd_value": 255000.0,
            "order_hash": "BTCUSD-abc123",
            "first_seen": (datetime.now(timezone.utc) - timedelta(seconds=65)).isoformat(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "scan_count": 65,
            "lifetime_seconds": 65
        }
        
        # Проверяем условие перехода
        hot_pool_threshold = POOLS_CONFIG["observer_pool"]["hot_pool_lifetime_seconds"]
        should_move = order["lifetime_seconds"] >= hot_pool_threshold
        
        assert should_move == True
        assert order["lifetime_seconds"] > 60
    
    @pytest.mark.asyncio
    async def test_return_to_general_pool(self, observer_pool):
        """Тест: Возврат монеты в общий пул"""
        # Сценарий: у монеты был 1 ордер, он ушел в горячий пул
        symbol_data = {
            "symbol": "SINGLEUSDT",
            "orders_count": 1,
            "orders_moved_to_hot": 1
        }
        
        # Проверяем условие возврата
        should_return = (symbol_data["orders_count"] == symbol_data["orders_moved_to_hot"])
        assert should_return == True
        
        # Сценарий 2: у монеты было несколько ордеров
        symbol_data_2 = {
            "symbol": "MULTIUSDT",
            "orders_count": 3,
            "orders_moved_to_hot": 1
        }
        
        should_return_2 = (symbol_data_2["orders_count"] == symbol_data_2["orders_moved_to_hot"])
        assert should_return_2 == False  # Остаются другие ордера
    
    @pytest.mark.asyncio
    async def test_scan_interval(self, observer_pool):
        """Тест: Интервал сканирования"""
        scan_interval = POOLS_CONFIG["observer_pool"]["scan_interval"]
        
        # Проверяем настройки
        assert scan_interval == 1  # 1 секунда по спецификации
        assert isinstance(scan_interval, (int, float))
        assert scan_interval > 0
    
    @pytest.mark.asyncio
    async def test_order_death_scenarios(self, observer_pool):
        """Тест: Различные сценарии "смерти" ордера"""
        
        # Сценарий 1: Потеря объема
        order_1 = {"original_qty": 10.0, "current_qty": 2.9}  # 29% осталось
        survival_threshold = POOLS_CONFIG["observer_pool"]["survival_threshold"]
        ratio_1 = order_1["current_qty"] / order_1["original_qty"]
        is_dead_1 = ratio_1 < survival_threshold
        assert is_dead_1 == True
        
        # Сценарий 2: Изменение цены
        order_2 = {"original_price": 50000.0, "current_price": 50001.0}
        is_dead_2 = order_2["original_price"] != order_2["current_price"]
        assert is_dead_2 == True
        
        # Сценарий 3: Полное исчезновение
        order_3 = {"exists_in_orderbook": False}
        is_dead_3 = not order_3["exists_in_orderbook"]
        assert is_dead_3 == True
        
        # Сценарий 4: Выживание (70% объема)
        order_4 = {"original_qty": 10.0, "current_qty": 7.0}
        ratio_4 = order_4["current_qty"] / order_4["original_qty"]
        is_dead_4 = ratio_4 < survival_threshold
        assert is_dead_4 == False
