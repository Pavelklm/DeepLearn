# 📊 Криптовалютный сканнер больших ордеров

Система реального времени для обнаружения и отслеживания крупных ордеров на криптовалютных биржах с WebSocket трансляцией данных.

## 🚀 Быстрый старт

### За 5 минут

```bash
# 1. Клонируйте и перейдите в директорию
cd Scanner

# 2. Создайте виртуальную среду
python -m venv venv
source venv/bin/activate  # Linux/Mac
# или
venv\Scripts\activate     # Windows

# 3. Установите зависимости
pip install -r requirements.txt

# 4. Настройте API ключи
cp .env.example .env
nano .env  # Добавьте ваши API ключи

# 5. Запустите тестовое сканирование
python main.py --primary-scan-only --symbols 5

# 6. Запустите полную систему
python main.py
```

### Тестовый WebSocket клиент

```javascript
const ws = new WebSocket('ws://localhost:8080/public');
ws.onmessage = (event) => {
    const data = JSON.parse(event.data);
    console.log('Diamond orders:', data);
};
```

## 🏗️ Архитектура системы

### Поток данных

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   Binance API   │───▶│ Primary Scanner  │───▶│ Observer Pool   │
│   (250 pairs)   │    │  (5 workers)     │    │ (1-3 workers)   │
└─────────────────┘    └──────────────────┘    └─────────────────┘
                                                        │
┌─────────────────┐    ┌──────────────────┐           │
│ WebSocket       │◀───│   Hot Pool       │◀──────────┘
│ Broadcaster     │    │ (1-8 workers)    │
└─────────────────┘    └──────────────────┘
```

### Этапы обработки

#### 📋 Этап 1: Первичное сканирование (Primary Scanner)
- **Цель**: Получить начальный снимок всех больших ордеров
- **Процесс**:
  1. Подключение к Binance API
  2. Получение топ-250 символов по объему торгов
  3. Исключение стейблкоинов (USDT, BUSD, USDC, FDUSD)
  4. Параллельное сканирование с 5 воркерами
  5. Определение "больших" ордеров (среднее топ-10 × 3.5)
  6. Генерация уникальных хэшей для каждого ордера

#### 📋 Этап 2: Пул наблюдателя (Observer Pool) 
- **Цель**: Отслеживание времени жизни ордеров
- **Логика**:
  - **"Тот же" ордер**: Та же цена + потеря < 70%
  - **"Смерть" ордера**: Изменение цены ИЛИ потеря > 70%
  - **Переход в Hot Pool**: Время жизни > 60 секунд
  - **Возврат в General Pool**: Все ордера исчезли

#### 📋 Этап 3: Горячий пул (Hot Pool)
- **Цель**: Максимальная аналитика для перспективных ордеров
- **Функции**:
  - Расчет весов по 6 алгоритмам
  - Категоризация: Basic (0-0.333), Gold (0.333-0.666), Diamond (0.666-1.0)
  - Множественные временные факторы
  - Рыночный контекст и аналитика
  - Real-time WebSocket трансляция

## ⚙️ Конфигурация

### Основная конфигурация (`config/main_config.py`)

```python
PRIMARY_SCAN_CONFIG = {
    "workers_count": 5,              # Воркеров для первичного сканирования
    "top_coins_limit": 250,          # Топ N монет по объему
    "large_order_multiplier": 3.5,   # Коэффициент "большого" ордера
    "orderbook_depth": 20,           # Глубина стакана
    "excluded_suffixes": ["USDT", "BUSD", "USDC", "FDUSD"]
}

POOLS_CONFIG = {
    "observer_pool": {
        "hot_pool_lifetime_seconds": 60,  # Время до Hot Pool
        "survival_threshold": 0.7          # Порог выживания (70%)
    },
    "hot_pool": {
        "max_workers": 8,                  # Максимум воркеров
        "min_scan_interval": 0.5           # Минимальный интервал
    }
}
```

### Веса и алгоритмы (`config/weights_config.py`)

```python
# Временные факторы
TIME_FACTORS = {
    "linear_1h": lambda t: min(t / 60, 1.0),
    "exponential_30m": lambda t: 1 - math.exp(-t / 30),
    "logarithmic_2h": lambda t: math.log(1 + t) / math.log(121),
    "adaptive_volatility": lambda t, vol: (1 - math.exp(-t / (30 * (1 + vol))))
}

# Алгоритмы финального веса
WEIGHT_ALGORITHMS = {
    "conservative": {"time_weight": 0.4, "size_weight": 0.25},
    "aggressive": {"time_weight": 0.2, "size_weight": 0.3},
    "hybrid": {"time_weight": 0.3, "size_weight": 0.25}
}
```

## 📊 API документация

### WebSocket эндпоинты

#### Приватный доступ
```
ws://server:8080/private?token=your_secret_token
```
- Полный доступ ко всем данным
- Без ограничений и задержек
- Все категории ордеров
- Расширенная аналитика

#### VIP доступ
```
ws://server:8080/vip?key=whitelisted_key
```
- Без rate limiting
- Все категории
- Полная аналитика
- Для избранных пользователей

#### Публичный доступ
```
ws://server:8080/public
```
- Rate limit: 10 сообщений/секунда
- Только Diamond категория
- Задержка 5 секунд

### Структура данных

#### Полная аналитическая структура ордера
```json
{
  "order_hash": "BTCUSDT-abc123",
  "symbol": "BTCUSDT", 
  "current_price": 65420.50,
  "order_price": 65500.00,
  "usd_value": 125000,
  "lifetime_seconds": 847,
  
  "time_factors": {
    "linear_1h": 0.235,
    "exponential_30m": 0.847,
    "logarithmic": 0.445,
    "adaptive": 0.689
  },
  
  "weights": {
    "conservative": 0.445,
    "aggressive": 0.789,
    "hybrid": 0.587,
    "recommended": 0.612
  },
  
  "categories": {
    "by_conservative": "gold",
    "by_aggressive": "diamond",
    "by_recommended": "diamond"
  },
  
  "market_context": {
    "symbol_volatility_1h": 0.0234,
    "market_volatility": 0.0445,
    "time_of_day_factor": 0.78,
    "weekend_factor": 0.65
  },
  
  "analytics": {
    "size_vs_average_top10": 8.90,
    "distance_to_round_level": 0.0012,
    "is_psycho_level": true,
    "historical_success_rate": 0.67
  }
}
```

#### Триггеры отправки WebSocket данных
- Новый ордер в горячем пуле
- Ордер исчез из горячего пула  
- Изменение категории ордера
- Изменение веса > 0.05
- Изменение USD value > 5%

## 🔧 Развертывание

### Ubuntu 22.04 Server

```bash
# Установка зависимостей
sudo apt update && sudo apt upgrade -y
sudo apt install python3.11 python3.11-venv nginx supervisor redis-server -y

# Создание пользователя
sudo useradd -m -s /bin/bash cryptoscanner
sudo usermod -aG sudo cryptoscanner

# Настройка приложения
cd /home/cryptoscanner
git clone <repository> Scanner
cd Scanner
python3.11 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# Настройка systemd сервиса
sudo cp deploy/cryptoscanner.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable cryptoscanner
sudo systemctl start cryptoscanner
```

### Nginx конфигурация

```nginx
server {
    listen 80;
    server_name your_domain.com;
    
    location /ws/ {
        proxy_pass http://127.0.0.1:8080;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
    }
}
```

### Docker (опционально)

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
CMD ["python", "main.py"]
```

## 🧪 Тестирование

### Запуск тестов

```bash
# Все тесты
pytest tests/ -v

# Конкретные тесты
pytest tests/test_primary_scanner.py -v
pytest tests/test_observer_pool.py -v  
pytest tests/test_hot_pool.py -v
pytest tests/test_integration.py -v

# С покрытием кода
pytest --cov=src tests/
```

### Тестовые сценарии

#### test_primary_scanner.py
- ✅ Получение списка торговых пар
- ✅ Фильтрация стейблкоинов
- ✅ Определение больших ордеров  
- ✅ Генерация хэшей
- ✅ Полное сканирование

#### test_observer_pool.py
- ✅ Ордер живет >1 минуты → переход в горячий пул
- ✅ Ордер теряет >70% → смерть ордера
- ✅ Повторное появление → новый хэш
- ✅ Адаптивные воркеры

#### test_hot_pool.py
- ✅ Расчет весов по всем алгоритмам
- ✅ Определение категорий (basic/gold/diamond)
- ✅ Временные факторы
- ✅ Полная аналитическая структура

#### test_integration.py
- ✅ Полный цикл: Primary → Observer → Hot Pool
- ✅ Смерть и воскрешение ордеров
- ✅ Категоризация Diamond/Gold/Basic
- ✅ Мультибиржевая архитектура

## 📈 Мониторинг

### Ключевые метрики

```python
CRITICAL_METRICS = {
    # Производительность
    "api_response_time": {"threshold": 2.0, "unit": "seconds"},
    "websocket_latency": {"threshold": 0.1, "unit": "seconds"},  
    "memory_usage": {"threshold": 80, "unit": "percent"},
    "cpu_usage": {"threshold": 90, "unit": "percent"},
    
    # Функциональность
    "active_orders_count": {"min": 1, "max": 10000},
    "diamond_orders_per_hour": {"min": 5},
    "failed_api_calls": {"threshold": 10, "period": "1min"}
}
```

### Health Check

```bash
# Проверка здоровья системы
python monitoring/health_check.py

# Просмотр метрик
cat data/monitoring.json | jq '.system_metrics'

# Алерты
python monitoring/alerts.py
```

### Логирование

```bash
# Основные логи
tail -f logs/scanner.log

# Ошибки
grep "ERROR" logs/scanner.log

# WebSocket активность  
tail -f logs/websocket.log

# Производительность
tail -f logs/performance.log | grep "hot_pool"
```

## ❓ FAQ

### Частые проблемы

**Q: Тесты падают с "Can't instantiate abstract class"**
```bash
# A: Установите pytest-asyncio
pip install pytest-asyncio

# Или добавьте в pytest.ini:
[tool:pytest]
asyncio_mode = auto
```

**Q: API ключи не работают**
```bash
# A: Проверьте .env файл
ls -la .env
cat .env | grep API_KEY

# Права доступа должны быть 600
chmod 600 .env
```

**Q: WebSocket соединение не устанавливается**
```bash
# A: Проверьте порт и firewall
netstat -tulpn | grep 8080
sudo ufw allow 8080
```

**Q: Нет Diamond ордеров**
```bash
# A: Уменьшите коэффициент в конфиге
# config/main_config.py
"large_order_multiplier": 2.0  # Вместо 3.5
```

### Команды управления

```bash
# Статус системы
python main.py --status

# Тестовый режим
python main.py --primary-scan-only --symbols 10

# Отладка
python main.py --dev

# Остановка
kill -SIGTERM $(cat /tmp/cryptoscanner.pid)

# Перезапуск
sudo systemctl restart cryptoscanner
```

### Производительность

| Компонент | Рекомендуемые ресурсы |
|-----------|----------------------|
| CPU       | 4+ cores             |
| RAM       | 8GB+                 |
| Диск      | SSD, 50GB+           |
| Сеть      | 100 Mbps+            |

### Структура файлов

```
Scanner/
├── config/              # Конфигурация
├── src/                 # Исходный код
│   ├── exchanges/       # API бирж
│   ├── pools/           # Пулы сканирования
│   ├── workers/         # Воркеры
│   ├── analytics/       # Аналитика
│   └── websocket/       # WebSocket сервер
├── tests/               # Тесты
├── data/                # Данные
│   ├── hot_pool_orders.json
│   └── cache/
├── logs/                # Логи
├── monitoring/          # Мониторинг
└── main.py             # Точка входа
```

## 🔗 Ссылки

- [Binance API Documentation](https://binance-docs.github.io/apidocs/futures/en/)
- [WebSocket RFC 6455](https://tools.ietf.org/html/rfc6455)
- [Python asyncio](https://docs.python.org/3/library/asyncio.html)
- [Pytest Documentation](https://docs.pytest.org/)

---

## 🏆 Особенности системы

### ✨ Уникальная архитектура
- **Трехэтапная обработка**: Primary → Observer → Hot Pool
- **Адаптивные воркеры**: Автоматическое масштабирование
- **Множественные алгоритмы весов**: 6 различных подходов к оценке
- **Real-time категоризация**: Basic/Gold/Diamond в реальном времени

### ⚡ Высокая производительность  
- **До 8 воркеров** в горячем пуле
- **Parallel scanning** с rate limiting protection
- **Эффективное кэширование** данных
- **WebSocket streaming** без задержек

### 🔒 Промышленная надежность
- **Graceful shutdown** с сохранением состояния
- **Retry логика** для API вызовов
- **Health monitoring** всех компонентов
- **Автоматические алерты** при проблемах

### 📡 Flexible WebSocket API
- **3 уровня доступа**: Private/VIP/Public
- **Rate limiting** для публичного доступа
- **Триггеры отправки** данных
- **Compression** и буферизация

---

**⚠️ Дисклеймер**: Система предназначена только для информационных целей. Не является инвестиционным советом.
