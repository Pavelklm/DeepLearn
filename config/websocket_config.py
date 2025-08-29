# =============================================================================
# НАСТРОЙКИ WEBSOCKET СЕРВЕРА
# =============================================================================

import os

WEBSOCKET_CONFIG = {
    # Сервер
    "host": "0.0.0.0",
    "port": 8080,
    "max_connections": 1000,
    
    # Аутентификация
    "private_token": "your_super_secret_private_token_2025",
    "vip_keys_file": "config/vip_keys.txt",  # Список VIP ключей
    
    # Rate limiting для публичного доступа
    "public_rate_limit": {
        "requests_per_second": 10,
        "burst_size": 20,
        "cleanup_interval": 60  # Очистка старых записей
    },
    
    # Задержки данных
    "data_delays": {
        "private": 0,      # Без задержек
        "vip": 0,          # Без задержек  
        "public": 5        # 5 секунд задержка
    },
    
    # Фильтры данных по типам доступа
    "access_filters": {
        "private": ["all"],  # Все данные
        "vip": ["basic", "gold", "diamond", "analytics"],
        "public": ["diamond"]  # Только diamond категория
    },
    
    # Heartbeat
    "ping_interval": 30,   # Пинг каждые 30 секунд
    "ping_timeout": 10,    # Таймаут ответа на пинг
    
    # Буферизация
    "message_buffer_size": 100,  # Буфер сообщений для отправки
    "compression": True,         # Сжатие сообщений
}

# Каналы подписки
SUBSCRIPTION_CHANNELS = {
    "hot_pool_updates": {
        "description": "Обновления горячего пула",
        "access_levels": ["private", "vip"],
        "rate_limit": None
    },
    
    "diamond_only": {
        "description": "Только diamond ордера", 
        "access_levels": ["private", "vip", "public"],
        "rate_limit": "public_rate_limit"
    },
    
    "market_analytics": {
        "description": "Аналитика рынка",
        "access_levels": ["private"],
        "rate_limit": None
    },
    
    "exchange_specific": {
        "description": "Данные по конкретной бирже",
        "access_levels": ["private", "vip"], 
        "parameters": ["exchange_name"],
        "rate_limit": None
    }
}
