# =============================================================================
# НАСТРОЙКИ БИРЖ
# =============================================================================

# ПОДДЕРЖИВАЕМЫЕ БИРЖИ
# =============================================================================
SUPPORTED_EXCHANGES = {
    "binance": {
        "name": "Binance Futures",
        "enabled": True,
        "api_class": "BinanceAPI",
        "base_url": "https://fapi.binance.com",
        "websocket_url": "wss://fstream.binance.com",
        "testnet": False
    },
    
    # Подготовка для будущих бирж
    "bybit": {
        "name": "Bybit Futures", 
        "enabled": False,
        "api_class": "BybitAPI",
        "base_url": "https://api.bybit.com",
        "websocket_url": "wss://stream.bybit.com",
        "testnet": False
    }
}

# НАСТРОЙКИ BINANCE
# =============================================================================
BINANCE_CONFIG = {
    # API настройки
    "api_timeout": 10,
    "max_retries": 3,
    "retry_delay": 1,
    
    # Rate limiting
    "requests_per_minute": 1200,
    "weight_per_minute": 6000,
    "requests_per_second": 10,
    
    # Веса запросов
    "endpoint_weights": {
        "exchangeInfo": 20,
        "depth": 50,
        "ticker/24hr": 40,
        "klines": 10
    },
    
    # Специфичные настройки
    "futures_only": True,
    "exclude_stablecoins": True,
    "min_volume_usdt": 100000,  # Минимальный объем для включения в сканирование
    
    # Тестовые настройки
    "testnet_url": "https://testnet.binancefuture.com"
}

# НАСТРОЙКИ BYBIT (для будущей интеграции)
# =============================================================================
BYBIT_CONFIG = {
    "api_timeout": 10,
    "max_retries": 3,
    "retry_delay": 1,
    "requests_per_minute": 600,
    "futures_only": True,
    "exclude_stablecoins": True,
    "min_volume_usdt": 50000
}

# ОБЩИЕ НАСТРОЙКИ МУЛЬТИБИРЖИ
# =============================================================================
MULTIEXCHANGE_CONFIG = {
    # Консолидация данных
    "consolidate_orders": True,
    "cross_exchange_analysis": True,
    "arbitrage_detection": False,  # Пока отключено
    
    # Приоритеты бирж (для консолидации)
    "exchange_priority": {
        "binance": 1.0,
        "bybit": 0.8
    },
    
    # Фильтры консолидации
    "min_exchanges_for_consolidation": 1,
    "duplicate_detection_threshold": 0.01,  # 1% разница в цене
    
    # Синхронизация
    "max_data_age_seconds": 5,
    "sync_timeout": 3
}

# КОНСТАНТЫ ФИЛЬТРАЦИИ
# =============================================================================
FILTERING_CONFIG = {
    # Исключаемые суффиксы (стейблкоины и другие)
    "excluded_suffixes": [
        "USDT", "BUSD", "USDC", "FDUSD", "TUSD", "USDP",
        "DAI", "FRAX", "LUSD"
    ],
    
    # Исключаемые префиксы
    "excluded_prefixes": [
        "1000"  # Например, 1000PEPEUSDT
    ],
    
    # Минимальные требования
    "min_24h_volume_usdt": 100000,
    "min_price_usdt": 0.000001,
    "max_price_usdt": 100000,
    
    # Список разрешенных пар (если нужна белая фильтрация)
    "whitelist_symbols": None,  # None = не используется
    
    # Черный список
    "blacklist_symbols": [
        # Добавить проблемные пары, если появятся
    ]
}
