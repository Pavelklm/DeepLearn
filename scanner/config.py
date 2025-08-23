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
    WHALE_MULTIPLIER = 40.0  # Коэффициент: большой_ордер = средний_ордер * коэффициент
    EXCLUDED_SYMBOLS = ["BTCUSDT", "ETHUSDT", "USDCUSDT"]  # Исключаем BTC и ETH
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
    WHALE_SYMBOLS_FILE = "whale_symbols.json"  # Файл со списком активных символов
    PERSISTENT_MODE = True  # Режим персистентного хранения
    
    # Настройки логирования
    VERBOSE_LOGS = True  # Детальные логи (оптимально для мониторинга)
    
    # ===== МНОГОУРОВНЕВОЕ СКАНИРОВАНИЕ =====
    
    # Горячий пул (активные киты)
    HOT_POOL_WORKERS = 5          # Воркеры для первого полного прохода
    HOT_POOL_DEDICATED_WORKER = 1 # Выделенный воркер для непрерывного сканирования китов
    HOT_SCAN_INTERVAL = 0         # Непрерывное сканирование (без пауз)
    
    # Пул наблюдения (недавно потерянные киты)
    WATCH_POOL_WORKER = 1         # Воркер для наблюдения
    WATCH_SCAN_INTERVAL = 10      # Секунды между сканами наблюдения
    WATCH_MAX_SCANS = 10          # Максимум сканов перед переводом в общий пул
    
    # Общий пул (все остальные символы)
    GENERAL_POOL_WORKERS = 3      # Воркеры для общего пула
    GENERAL_SCAN_INTERVAL = 30    # Секунды между общими сканами
    
    # Общие настройки многоуровневого режима
    MULTI_LEVEL_MODE = True       # Включить многоуровневое сканирование
    INITIAL_FULL_SCAN = True      # Делать ли полный скан при старте
    
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
            "limit": 300  # Оптимальная глубина стакана
        }
