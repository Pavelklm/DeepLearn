#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Конфигурация для сканера больших ордеров Binance Futures
"""

class ScannerConfig:
    """Конфигурация сканера"""
    
    # API настройки
    BASE_URL = "https://fapi.binance.com"
    
    # Основные параметры сканирования
    MIN_ORDER_SIZE_USD = 500000  # Минимальный размер ордера в USD
    EXCLUDED_SYMBOLS = ["BTCUSDT", "ETHUSDT"]  # Исключаем BTC и ETH
    MAX_ORDERS_PER_SIDE = 3  # Максимум 3 ордера на покупку и 3 на продажу
    VOLATILITY_MULTIPLIER = 3.0  # Коэффициент для расчета динамического радиуса на основе волатильности
    TOP_SYMBOLS_COUNT = 250  # Количество топ символов по объему торгов
    
    # Технические настройки
    REQUEST_DELAY = 0  # Задержка между запросами
    MAX_WORKERS = 5  # Количество параллельных воркеров
    PRICE_TOLERANCE = 0.0001  # Допустимое изменение цены (0.01%)
    
    # Настройки HTTP запросов
    MAX_RETRIES = 3
    REQUEST_TIMEOUT = 10
    
    # Настройки персистентности
    DATA_FILE = "big_orders_data.json"
    PERSISTENT_MODE = True  # Режим персистентного хранения
    
    # Настройки логирования
    VERBOSE_LOGS = True  # Детальные логи (оптимально для мониторинга)
    
    @classmethod
    def get_klines_params(cls, symbol: str) -> dict:
        """Параметры для запроса свечей"""
        return {
            "symbol": symbol,
            "interval": "5m", 
            "limit": 12
        }
    
    @classmethod
    def get_depth_params(cls, symbol: str) -> dict:
        """Параметры для запроса стакана ордеров"""
        return {
            "symbol": symbol,
            "limit": 500  # Оптимальная глубина стакана
        }
