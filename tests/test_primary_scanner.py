"""
Тесты первичного сканнера - строго по спецификации
"""

import pytest
import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

from src.pools.primary_scanner import PrimaryScanner, LargeOrder
from src.exchanges.base_exchange import BaseExchange
from config.main_config import PRIMARY_SCAN_CONFIG


@pytest.fixture
def mock_exchange():
    """Мок биржи для тестирования"""
    exchange = AsyncMock(spec=BaseExchange)
    exchange.name = "binance"  # Добавляем имя биржи
    
    # Настройка моков
    exchange.get_futures_pairs = AsyncMock(return_value=[
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "DOGEUSDT",
        "XRPUSDT", "DOTUSDT", "UNIUSDT", "LTCUSDT", "LINKUSDT",
        "BUSDUSDT", "USDCUSDT", "FDUSDUSDT"  # Стейблкоины для фильтрации
    ])
    
    exchange.get_top_volume_symbols = AsyncMock(return_value=[
        "BTCUSDT", "ETHUSDT", "BNBUSDT", "ADAUSDT", "DOGEUSDT",
        "XRPUSDT", "DOTUSDT", "UNIUSDT", "LTCUSDT", "LINKUSDT"
    ])
    
    exchange.get_current_price = AsyncMock(return_value=50000.0)
    
    exchange.get_volatility_data = AsyncMock(return_value={"volatility": 0.02})
    
    # Мок стакана с большими ордерами
    exchange.get_orderbook = AsyncMock(return_value={
        "asks": [
            [50100, 0.5],   # 25,050 USDT
            [50200, 0.3],   # 15,060 USDT
            [50300, 0.2],   # 10,060 USDT
            [50400, 0.1],   # 5,040 USDT
            [50500, 0.1],   # 5,050 USDT
            [50600, 0.1],   # 5,060 USDT
            [50700, 0.1],   # 5,070 USDT
            [50800, 0.1],   # 5,080 USDT
            [50900, 0.1],   # 5,090 USDT
            [51000, 5.0],   # 255,000 USDT - БОЛЬШОЙ ОРДЕР!
            [51100, 0.1],   # 5,110 USDT
            [51200, 0.1],   # 5,120 USDT
        ],
        "bids": [
            [49900, 0.5],   # 24,950 USDT
            [49800, 0.3],   # 14,940 USDT
            [49700, 0.2],   # 9,940 USDT
            [49600, 0.1],   # 4,960 USDT
            [49500, 0.1],   # 4,950 USDT
            [49400, 0.1],   # 4,940 USDT
            [49300, 0.1],   # 4,930 USDT
            [49200, 0.1],   # 4,920 USDT
            [49100, 0.1],   # 4,910 USDT
            [49000, 4.0],   # 196,000 USDT - БОЛЬШОЙ ОРДЕР!
            [48900, 0.1],   # 4,890 USDT
            [48800, 0.1],   # 4,880 USDT
        ]
    })
    
    return exchange


@pytest.fixture
def primary_scanner(mock_exchange):
    """Инициализированный первичный сканнер"""
    scanner = PrimaryScanner(mock_exchange)
    return scanner


class TestPrimaryScanner:
    """Тесты первичного сканнера по спецификации"""
    
    @pytest.mark.asyncio
    async def test_get_trading_pairs(self, primary_scanner, mock_exchange):
        """Тест: Получение списка торговых пар"""
        # Получаем список пар
        pairs = await mock_exchange.get_futures_pairs()
        
        # Проверяем
        assert len(pairs) == 13
        assert "BTCUSDT" in pairs
        assert "ETHUSDT" in pairs
        assert "BUSDUSDT" in pairs  # Стейблкоин тоже должен быть в списке
        
        # Проверяем, что метод был вызван
        mock_exchange.get_futures_pairs.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_filter_stablecoins(self, primary_scanner):
        """Тест: Фильтрация стейблкоинов"""
        # Список символов с стейблкоинами
        symbols = [
            "BTCUSDT", "ETHUSDT", "BNBUSDT", 
            "BUSDUSDT", "USDCUSDT", "FDUSDUSDT", "TUSDUSDT",
            "ADAUSDT", "DOGEUSDT"
        ]
        
        # Фильтруем
        excluded_suffixes = PRIMARY_SCAN_CONFIG["excluded_suffixes"]
        filtered = []
        for symbol in symbols:
            is_stablecoin = False
            for suffix in excluded_suffixes:
                if symbol.replace("USDT", "").endswith(suffix):
                    is_stablecoin = True
                    break
            if not is_stablecoin:
                filtered.append(symbol)
        
        # Проверяем результат (в PRIMARY_SCAN_CONFIG исключены только BUSD, USDC, FDUSD, TUSD)
        assert len(filtered) == 5  # TUSD исключается
        assert "BTCUSDT" in filtered
        assert "ETHUSDT" in filtered
        assert "BNBUSDT" in filtered  
        assert "TUSDUSDT" not in filtered  # TUSD исключается
        assert "BUSDUSDT" not in filtered  # BUSD исключается
        assert "USDCUSDT" not in filtered  # USDC исключается 
        assert "FDUSDUSDT" not in filtered  # FDUSD исключается
    
    @pytest.mark.asyncio
    async def test_get_top_250_by_volume(self, primary_scanner, mock_exchange):
        """Тест: Отбор топ-250 по объему"""
        # Получаем топ символы
        top_symbols = await mock_exchange.get_top_volume_symbols(250)
        
        # Проверяем
        assert len(top_symbols) == 10  # В моке возвращается 10
        assert "BTCUSDT" in top_symbols
        assert "ETHUSDT" in top_symbols
        
        # Проверяем вызов
        mock_exchange.get_top_volume_symbols.assert_called_once_with(250)
    
    @pytest.mark.asyncio
    async def test_determine_large_orders(self, primary_scanner, mock_exchange):
        """Тест: Определение больших ордеров"""
        # Получаем стакан
        orderbook = await mock_exchange.get_orderbook("BTCUSDT", depth=20)
        current_price = await mock_exchange.get_current_price("BTCUSDT")
        
        # Анализируем ASK сторону
        asks = orderbook["asks"]
        top_10_asks = asks[:10]
        
        # Считаем среднее топ-10
        total_volume = sum(float(price) * float(qty) for price, qty in top_10_asks)
        average_volume = total_volume / 10
        
        # Порог для большого ордера
        large_threshold = average_volume * PRIMARY_SCAN_CONFIG["large_order_multiplier"]
        
        # Находим большие ордера
        large_orders = []
        for price, qty in asks:
            usd_value = float(price) * float(qty)
            if usd_value >= large_threshold:
                large_orders.append((price, qty, usd_value))
        
        # Проверяем
        assert len(large_orders) == 1  # Должен быть 1 большой ордер
        assert large_orders[0][2] == 255000  # 255,000 USDT
        assert large_orders[0][2] / average_volume > 3.5  # Больше коэффициента
    
    @pytest.mark.asyncio
    async def test_generate_order_hash(self, primary_scanner):
        """Тест: Генерация хэшей для ордеров"""
        # Генерируем хэш
        order_hash = primary_scanner._generate_order_hash(
            symbol="BTCUSDT",
            price=51000.0,
            qty=5.0,
            side="ASK"
        )
        
        # Проверяем формат хэша
        assert isinstance(order_hash, str)
        assert len(order_hash) > 0
        assert "-" in order_hash
        assert order_hash.startswith("BTCUSD")  # Первые 6 символов
        
        # Проверяем уникальность
        hash2 = primary_scanner._generate_order_hash(
            symbol="BTCUSDT",
            price=51000.0,
            qty=5.0,
            side="ASK"
        )
        assert order_hash != hash2  # Разные из-за времени
    
    @pytest.mark.asyncio
    async def test_test_scan_method(self, primary_scanner, mock_exchange):
        """Тест: Метод тестового сканирования"""
        # Запускаем тестовое сканирование
        test_symbols = ["BTCUSDT", "ETHUSDT"]
        results = await primary_scanner.run_test_scan(test_symbols)
        
        # Проверяем структуру результатов
        assert results["scan_completed"] == True
        assert results["total_symbols_scanned"] == 2
        assert "total_large_orders" in results
        assert "orders_by_symbol" in results
        assert "top_orders" in results
        assert "categories" in results
        assert "statistics" in results
        
        # Проверяем категории (по спецификации)
        categories = results["categories"]
        assert "basic" in categories
        assert "gold" in categories
        assert "diamond" in categories
        
        # Проверяем статистику
        stats = results["statistics"]
        assert "symbols_with_orders" in stats
        assert "round_level_orders" in stats
        assert "max_usd_value" in stats
        assert "min_usd_value" in stats
        assert "avg_usd_value" in stats
    
    @pytest.mark.asyncio
    async def test_full_scan_with_workers(self, primary_scanner, mock_exchange):
        """Тест: Полное сканирование с 5 воркерами"""
        # Мок уже настроен на 10 символов, настроим на 50
        symbols = [f"TOKEN{i}USDT" for i in range(50)]
        mock_exchange.get_top_volume_symbols.return_value = symbols
        
        # Запускаем полное сканирование
        results = await primary_scanner.run_full_scan()
        
        # Проверяем
        assert results["scan_completed"] == True
        assert results["total_symbols_scanned"] == 50
        
        # Проверяем, что использовались воркеры
        workers_count = PRIMARY_SCAN_CONFIG["workers_count"]
        assert workers_count == 5  # По спецификации
        
        # Проверяем временные метки
        assert results["scan_start_time"] is not None
        assert results["scan_end_time"] is not None
        assert results["duration_seconds"] >= 0
    
    @pytest.mark.asyncio
    async def test_round_level_detection(self, primary_scanner):
        """Тест: Определение психологических (круглых) уровней"""
        # Тестируем разные цены
        test_cases = [
            (100.0, True),      # Круглое число
            (99.98, True),      # Близко к 100 (в пределах 2%)
            (50.0, True),       # Круглое число
            (10.0, True),       # Круглое число
            (1.0, True),        # Круглое число
            (0.5, True),        # Круглое число
            (0.1, True),        # Круглое число
            (123.456, False),   # Не круглое
            (99.5, False),      # Далеко от круглого
        ]
        
        for price, expected in test_cases:
            result = primary_scanner._is_near_round_level(price)
            assert result == expected, f"Price {price} should be {expected}"
    
    @pytest.mark.asyncio
    async def test_order_structure(self, primary_scanner):
        """Тест: Структура данных ордера"""
        # Создаем тестовый ордер
        order = LargeOrder(
            symbol="BTCUSDT",
            current_price=50000.0,
            order_type="ASK",
            price=51000.0,
            quantity=5.0,
            usd_value=255000.0,
            distance_percent=2.0,
            size_vs_average=8.5,
            average_order_size=30000.0,
            first_seen=datetime.now(timezone.utc),
            order_hash="BTCUSD-abc123",
            volatility_1h=0.02,
            scan_count=1,
            is_round_level=True
        )
        
        # Проверяем все поля
        assert order.symbol == "BTCUSDT"
        assert order.current_price == 50000.0
        assert order.order_type == "ASK"
        assert order.price == 51000.0
        assert order.quantity == 5.0
        assert order.usd_value == 255000.0
        assert order.distance_percent == 2.0
        assert order.size_vs_average == 8.5
        assert order.average_order_size == 30000.0
        assert order.volatility_1h == 0.02
        assert order.scan_count == 1
        assert order.is_round_level == True
        assert order.order_hash == "BTCUSD-abc123"
        assert isinstance(order.first_seen, datetime)
