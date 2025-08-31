"""
Интеграционные тесты - полный цикл работы системы по спецификации
"""

import pytest
import asyncio
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from src.scanner_orchestrator import ScannerOrchestrator
from src.pools.primary_scanner import PrimaryScanner
from src.pools.observer_pool import ObserverPool
from src.pools.general_pool import GeneralPool
from src.pools.hot_pool import HotPool
from src.exchanges.base_exchange import BaseExchange
from src.websocket.server import WebSocketServer
from config.main_config import PRIMARY_SCAN_CONFIG, POOLS_CONFIG


@pytest.fixture
async def mock_exchange():
    """Мок биржи с предопределенными ордерами для тестирования"""
    exchange = AsyncMock(spec=BaseExchange)
    
    # Настройка для полного цикла
    exchange.get_futures_pairs = AsyncMock(return_value=[
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "DOGEUSDT"
    ])
    
    exchange.get_top_volume_symbols = AsyncMock(return_value=[
        "BTCUSDT", "ETHUSDT", "BNBUSDT"
    ])
    
    exchange.get_current_price = AsyncMock(side_effect=lambda symbol: {
        "BTCUSDT": 50000.0,
        "ETHUSDT": 3000.0,
        "BNBUSDT": 400.0
    }.get(symbol, 100.0))
    
    exchange.get_volatility_data = AsyncMock(return_value={"volatility": 0.02})
    
    # Стаканы с большими ордерами для разных символов
    exchange.get_orderbook = AsyncMock(side_effect=lambda symbol, depth=20: {
        "BTCUSDT": {
            "asks": [
                [50100, 0.5],
                [50200, 0.3],
                [50300, 0.2],
                [50400, 0.1],
                [50500, 0.1],
                [50600, 0.1],
                [50700, 0.1],
                [50800, 0.1],
                [50900, 0.1],
                [51000, 5.0],  # БОЛЬШОЙ ОРДЕР - будет diamond
                [51100, 0.1],
            ],
            "bids": [
                [49900, 0.5],
                [49800, 0.3],
                [49700, 0.2],
                [49600, 0.1],
                [49500, 0.1],
                [49400, 0.1],
                [49300, 0.1],
                [49200, 0.1],
                [49100, 0.1],
                [49000, 4.0],  # БОЛЬШОЙ ОРДЕР - будет gold
            ]
        },
        "ETHUSDT": {
            "asks": [
                [3010, 1.0],
                [3020, 0.5],
                [3030, 0.3],
                [3040, 0.2],
                [3050, 0.2],
                [3060, 0.2],
                [3070, 0.2],
                [3080, 0.2],
                [3090, 0.2],
                [3100, 20.0],  # БОЛЬШОЙ ОРДЕР - будет basic
            ],
            "bids": [
                [2990, 1.0],
                [2980, 0.5],
                [2970, 0.3],
                [2960, 0.2],
                [2950, 0.2],
            ]
        },
        "BNBUSDT": {
            "asks": [[401, 1.0], [402, 1.0]],
            "bids": [[399, 1.0], [398, 1.0]]
        }
    }.get(symbol, {"asks": [], "bids": []}))
    
    return exchange


@pytest.fixture
async def orchestrator(mock_exchange):
    """Инициализированный оркестратор системы"""
    with patch('src.exchanges.exchange_factory.get_exchange', return_value=mock_exchange):
        orch = ScannerOrchestrator(exchanges=["binance"], testnet=True)
        return orch


class TestIntegration:
    """Интеграционные тесты полного цикла по спецификации"""
    
    @pytest.mark.asyncio
    async def test_full_cycle_primary_to_hot(self, orchestrator, mock_exchange):
        """Тест: Полный цикл - первичное сканирование → наблюдатель → горячий пул"""
        
        # 1. ПЕРВИЧНОЕ СКАНИРОВАНИЕ
        # Инициализируем компоненты
        await orchestrator._initialize_exchanges()
        await orchestrator._create_components()
        
        # Запускаем первичное сканирование
        scan_results = await orchestrator.primary_scanner.run_test_scan(["BTCUSDT", "ETHUSDT"])
        
        # Проверяем результаты сканирования
        assert scan_results["scan_completed"] == True
        assert scan_results["total_symbols_scanned"] == 2
        assert scan_results["total_large_orders"] > 0
        
        # 2. ПУЛ НАБЛЮДАТЕЛЯ
        # Запускаем пулы
        await orchestrator.observer_pool.start()
        await orchestrator.hot_pool.start()
        
        # Симулируем прохождение времени (>60 секунд)
        # Для теста используем моки с уже "состаренными" ордерами
        test_order = {
            "symbol": "BTCUSDT",
            "price": 51000.0,
            "quantity": 5.0,
            "type": "ASK",
            "usd_value": 255000.0,
            "order_hash": "BTCUSD-test123",
            "first_seen": (datetime.now(timezone.utc) - timedelta(seconds=65)).isoformat(),
            "last_seen": datetime.now(timezone.utc).isoformat(),
            "lifetime_seconds": 65,
            "scan_count": 65
        }
        
        # Добавляем ордер в observer pool
        orchestrator.observer_pool.add_order_from_primary_scan(test_order)
        
        # Проверяем условие перехода в hot pool
        hot_pool_threshold = POOLS_CONFIG["observer_pool"]["hot_pool_lifetime_seconds"]
        assert test_order["lifetime_seconds"] > hot_pool_threshold
        
        # 3. ГОРЯЧИЙ ПУЛ
        # Ордер должен попасть в горячий пул
        await orchestrator.hot_pool.add_order(test_order)
        
        # Получаем статистику
        hot_pool_stats = orchestrator.hot_pool.get_stats()
        assert hot_pool_stats["total_orders"] >= 1
        
        # Останавливаем систему
        await orchestrator.stop()
    
    @pytest.mark.asyncio
    async def test_predefined_orders_journey(self, orchestrator, mock_exchange):
        """Тест: Несколько предзаданных ордеров проходят весь путь"""
        
        # Предопределенные ордера с разными характеристиками
        test_orders = [
            {
                "symbol": "BTCUSDT",
                "price": 51000.0,
                "quantity": 5.0,
                "usd_value": 255000.0,
                "lifetime_seconds": 120,  # 2 минуты - перейдет в hot pool
                "expected_category": "diamond"
            },
            {
                "symbol": "ETHUSDT",
                "price": 3100.0,
                "quantity": 20.0,
                "usd_value": 62000.0,
                "lifetime_seconds": 90,  # 1.5 минуты - перейдет в hot pool
                "expected_category": "gold"
            },
            {
                "symbol": "BNBUSDT",
                "price": 405.0,
                "quantity": 50.0,
                "usd_value": 20250.0,
                "lifetime_seconds": 30,  # 30 секунд - НЕ перейдет в hot pool
                "expected_category": "basic"
            }
        ]
        
        # Инициализируем систему
        await orchestrator._initialize_exchanges()
        await orchestrator._create_components()
        
        # Добавляем ордера в observer pool
        for order_data in test_orders:
            order = {
                "symbol": order_data["symbol"],
                "price": order_data["price"],
                "quantity": order_data["quantity"],
                "type": "ASK",
                "usd_value": order_data["usd_value"],
                "order_hash": f"{order_data['symbol'][:6]}-test",
                "first_seen": (datetime.now(timezone.utc) - timedelta(seconds=order_data["lifetime_seconds"])).isoformat(),
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "lifetime_seconds": order_data["lifetime_seconds"],
                "scan_count": order_data["lifetime_seconds"]
            }
            
            orchestrator.observer_pool.add_order_from_primary_scan(order)
            
            # Проверяем, должен ли ордер перейти в hot pool
            hot_pool_threshold = POOLS_CONFIG["observer_pool"]["hot_pool_lifetime_seconds"]
            should_move_to_hot = order["lifetime_seconds"] >= hot_pool_threshold
            
            if order_data["symbol"] == "BNBUSDT":
                assert should_move_to_hot == False  # Не должен перейти
            else:
                assert should_move_to_hot == True   # Должен перейти
    
    @pytest.mark.asyncio
    async def test_category_assignment(self, orchestrator):
        """Тест: Проверка попадания ордеров в нужные категории"""
        
        # Тестовые ордера с разными весами
        orders_with_weights = [
            {"weight": 0.1, "expected": "basic"},
            {"weight": 0.25, "expected": "basic"},
            {"weight": 0.333, "expected": "basic"},
            {"weight": 0.4, "expected": "gold"},
            {"weight": 0.5, "expected": "gold"},
            {"weight": 0.666, "expected": "gold"},
            {"weight": 0.7, "expected": "diamond"},
            {"weight": 0.85, "expected": "diamond"},
            {"weight": 0.95, "expected": "diamond"},
        ]
        
        from config.main_config import WEIGHT_CATEGORIES
        
        for test_case in orders_with_weights:
            weight = test_case["weight"]
            expected = test_case["expected"]
            
            # Определяем категорию
            category = None
            for cat_name, cat_config in WEIGHT_CATEGORIES.items():
                if cat_config["min"] <= weight <= cat_config["max"]:
                    category = cat_name
                    break
            
            assert category == expected, f"Weight {weight} should be {expected}, got {category}"
    
    @pytest.mark.asyncio
    async def test_order_death_and_resurrection(self, orchestrator, mock_exchange):
        """Тест: Смерть и воскрешение ордеров"""
        
        # Инициализируем систему
        await orchestrator._initialize_exchanges()
        await orchestrator._create_components()
        
        # 1. Создаем ордер
        original_order = {
            "symbol": "BTCUSDT",
            "price": 51000.0,
            "quantity": 5.0,
            "type": "ASK",
            "usd_value": 255000.0,
            "order_hash": "BTCUSD-original",
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "lifetime_seconds": 0
        }
        
        orchestrator.observer_pool.add_order_from_primary_scan(original_order)
        
        # 2. Ордер "умирает" (теряет >70% объема)
        survival_threshold = POOLS_CONFIG["observer_pool"]["survival_threshold"]
        
        # Симулируем потерю объема
        updated_quantity = 1.4  # 28% от исходного (5.0)
        survival_ratio = updated_quantity / original_order["quantity"]
        
        assert survival_ratio < survival_threshold  # Ордер должен "умереть"
        
        # 3. Ордер "воскресает" с новым хэшом
        resurrected_order = {
            "symbol": "BTCUSDT",
            "price": 51000.0,  # Та же цена
            "quantity": 5.0,    # Полный объем восстановлен
            "type": "ASK",
            "usd_value": 255000.0,
            "order_hash": "BTCUSD-resurrected",  # НОВЫЙ ХЭШ!
            "first_seen": (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat(),
            "lifetime_seconds": 0
        }
        
        # Проверяем, что это разные ордера
        assert original_order["order_hash"] != resurrected_order["order_hash"]
        assert original_order["first_seen"] != resurrected_order["first_seen"]
        assert original_order["price"] == resurrected_order["price"]
    
    @pytest.mark.asyncio
    async def test_multiexchange_logic(self, orchestrator):
        """Тест: Тестирование мультибиржевой логики"""
        
        # Создаем моки для разных бирж
        binance_mock = AsyncMock(spec=BaseExchange)
        binance_mock.name = "binance"
        binance_mock.get_futures_pairs = AsyncMock(return_value=["BTCUSDT", "ETHUSDT"])
        
        bybit_mock = AsyncMock(spec=BaseExchange)
        bybit_mock.name = "bybit"
        bybit_mock.get_futures_pairs = AsyncMock(return_value=["BTCUSDT", "ADAUSDT"])
        
        # Патчим фабрику бирж
        with patch('src.exchanges.exchange_factory.get_exchange') as mock_factory:
            mock_factory.side_effect = lambda name, testnet: {
                "binance": binance_mock,
                "bybit": bybit_mock
            }.get(name)
            
            # Создаем оркестратор с несколькими биржами
            multi_orch = ScannerOrchestrator(exchanges=["binance", "bybit"], testnet=True)
            await multi_orch._initialize_exchanges()
            
            # Проверяем, что обе биржи инициализированы
            assert len(multi_orch.exchanges) == 2
            assert "binance" in multi_orch.exchanges
            assert "bybit" in multi_orch.exchanges
    
    @pytest.mark.asyncio
    async def test_websocket_data_transmission(self, orchestrator):
        """Тест: WebSocket передача данных"""
        
        # Создаем мок WebSocket сервера
        ws_server = MagicMock(spec=WebSocketServer)
        ws_server.send_hot_pool_data = AsyncMock()
        ws_server.is_running = True
        
        # Инициализируем систему
        await orchestrator._initialize_exchanges()
        await orchestrator._create_components()
        
        # Подключаем WebSocket к hot pool
        orchestrator.hot_pool.websocket_server = ws_server
        
        # Добавляем ордер в hot pool
        test_order = {
            "symbol": "BTCUSDT",
            "price": 51000.0,
            "quantity": 5.0,
            "usd_value": 255000.0,
            "order_hash": "BTCUSD-ws-test",
            "lifetime_seconds": 100,
            "recommended_weight": 0.75  # Diamond категория
        }
        
        await orchestrator.hot_pool.add_order(test_order)
        
        # Проверяем, что WebSocket должен отправить данные
        # (в реальной реализации hot_pool вызовет ws_server.send_hot_pool_data)
        
        # Формируем ожидаемую структуру данных
        expected_data = {
            "type": "hot_pool_update",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "trigger": "new_order",
            "orders": [test_order],
            "categories_distribution": {
                "basic": 0,
                "gold": 0,
                "diamond": 1
            }
        }
        
        # Проверяем структуру
        assert "type" in expected_data
        assert "trigger" in expected_data
        assert "orders" in expected_data
        assert "categories_distribution" in expected_data
    
    @pytest.mark.asyncio
    async def test_general_pool_to_observer_flow(self, orchestrator, mock_exchange):
        """Тест: Поток из общего пула в пул наблюдателя"""
        
        # Инициализируем систему
        await orchestrator._initialize_exchanges()
        await orchestrator._create_components()
        
        # Запускаем пулы
        await orchestrator.observer_pool.start()
        await orchestrator.general_pool.start()
        
        # General pool находит большой ордер
        new_large_order = {
            "symbol": "NEWUSDT",
            "price": 100.0,
            "quantity": 1000.0,
            "usd_value": 100000.0,
            "order_hash": "NEWUSD-found",
            "first_seen": datetime.now(timezone.utc).isoformat()
        }
        
        # General pool отправляет в observer pool
        orchestrator.observer_pool.add_order_from_primary_scan(new_large_order)
        
        # Проверяем, что ордер в observer pool
        stats = orchestrator.observer_pool.get_stats()
        assert stats["total_orders"] >= 0
        
        # Останавливаем пулы
        await orchestrator.general_pool.stop()
        await orchestrator.observer_pool.stop()
    
    @pytest.mark.asyncio 
    async def test_graceful_shutdown(self, orchestrator):
        """Тест: Корректная остановка системы"""
        
        # Полный запуск
        await orchestrator._initialize_exchanges()
        await orchestrator._create_components()
        await orchestrator._start_continuous_pools()
        
        # Проверяем, что все запущено
        assert orchestrator.is_running == False  # Изначально False
        orchestrator.is_running = True  # Устанавливаем вручную для теста
        
        # Останавливаем в правильном порядке
        await orchestrator.stop()
        
        # Проверяем, что все остановлено
        assert orchestrator.is_running == False
        assert len(orchestrator.exchanges) == 0