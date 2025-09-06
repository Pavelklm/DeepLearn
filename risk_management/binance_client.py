"""Клиент для работы с Binance API с ретраями и безопасной обработкой ошибок"""
import logging
import time
import random
from functools import wraps
from typing import Dict, Any, Set, List
import pandas as pd
from binance.client import Client
from binance.exceptions import BinanceAPIException, BinanceOrderException
import requests.exceptions

logger = logging.getLogger(__name__)

# ... (декораторы и константы остаются без изменений) ...
RETRYABLE_ERROR_CODES: Set[int] = {-1021, -1001, -1003, -2010, -2015}
NETWORK_ERRORS = (
    ConnectionError,
    TimeoutError,
    requests.exceptions.RequestException,
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError
)

def calc_wait_time(attempt: int, delay: float = 1.0, backoff: float = 2.0) -> float:
    return delay * (backoff ** (attempt - 1)) + random.uniform(0, 1)

def retry_safe_operations(max_attempts: int = 3, delay: float = 1.0, backoff: float = 2.0):
    """Декоратор для безопасных операций: баланс, статус ордера"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            attempt = 0
            while attempt < max_attempts:
                try:
                    return func(*args, **kwargs)
                except NETWORK_ERRORS as e:
                    attempt += 1
                    wait = calc_wait_time(attempt, delay, backoff)
                    logger.warning(f"[{func.__name__}] Сетевая ошибка: {e}. Попытка {attempt}/{max_attempts}. Ждем {wait:.1f}s")
                    time.sleep(wait)
                except BinanceAPIException as e:
                    if e.code in RETRYABLE_ERROR_CODES:
                        attempt += 1
                        wait = calc_wait_time(attempt, delay, backoff)
                        logger.warning(f"[{func.__name__}] Retryable API ошибка: {e}. Попытка {attempt}/{max_attempts}. Ждем {wait:.1f}s")
                        time.sleep(wait)
                    else:
                        logger.error(f"[{func.__name__}] Non-retryable API ошибка: {e}")
                        raise
                except Exception as e:
                    logger.error(f"[{func.__name__}] Неожиданная ошибка: {e}")
                    raise
            raise RuntimeError(f"[{func.__name__}] Не удалось выполнить после {max_attempts} попыток")
        return wrapper
    return decorator

def retry_network_sensitive(max_attempts: int = 2, delay: float = 1.0):
    """Декоратор для критичных операций: place/cancel ордера"""
    def decorator(func):
        @wraps(func)
        def wrapper(self, *args, **kwargs):
            attempt = 0
            while attempt < max_attempts:
                try:
                    return func(self, *args, **kwargs)
                except NETWORK_ERRORS as e:
                    attempt += 1
                    symbol = args[0] if len(args) > 0 else kwargs.get("symbol")
                    order_id = args[1] if len(args) > 1 else kwargs.get("order_id")
                    if func.__name__ == "cancel_order" and symbol and order_id:
                        try:
                            status = self.get_order_status(symbol, order_id)
                            if status.get("status") in ("CANCELED", "FILLED"):
                                logger.info(f"Order {order_id} уже завершен ({status.get('status')}) после сетевого сбоя")
                                return status
                        except Exception as check_err:
                            logger.warning(f"Не удалось проверить статус ордера {order_id}: {check_err}")
                    if attempt >= max_attempts:
                        logger.error(f"[{func.__name__}] Сетевая ошибка после {max_attempts} попыток: {e}")
                        raise
                    wait = delay + random.uniform(0, 1)
                    logger.warning(f"[{func.__name__}] Сетевая ошибка: {e}. Попытка {attempt}/{max_attempts}. Ждем {wait:.1f}s")
                    time.sleep(wait)
                except (BinanceAPIException, BinanceOrderException) as e:
                    logger.error(f"[{func.__name__}] API ошибка: {e}")
                    raise
                except Exception as e:
                    logger.error(f"[{func.__name__}] Неожиданная ошибка: {e}")
                    raise
            raise RuntimeError(f"[{func.__name__}] Не удалось выполнить после {max_attempts} попыток")
        return wrapper
    return decorator


class BinanceClient:
    def __init__(self, api_key: str, api_secret: str):
        self.client = Client(api_key, api_secret, requests_params={"timeout": 30})
        logger.info("Binance клиент инициализирован с таймаутом 30с")

    @retry_safe_operations()
    def get_account_balance(self, asset: str = "USDT") -> float:
        logger.info(f"Запрос баланса для {asset}")
        account_info = self.client.get_account()
        for b in account_info.get('balances', []):
            if b['asset'] == asset:
                balance = float(b['free'])
                logger.info(f"Баланс {asset}: {balance}")
                return balance
        logger.warning(f"Актив {asset} не найден, возвращаем 0")
        return 0.0

    # ⭐ НОВЫЙ МЕТОД
    @retry_safe_operations()
    def get_historical_klines(self, symbol: str, interval: str, limit: int) -> pd.DataFrame:
        """Получает исторические данные и возвращает их в виде DataFrame."""
        logger.info(f"Запрос {limit} свечей для {symbol} с интервалом {interval}")
        klines = self.client.get_klines(symbol=symbol, interval=interval, limit=limit)
        
        # Преобразуем данные в DataFrame
        df = pd.DataFrame(klines, columns=[
            'Open time', 'Open', 'High', 'Low', 'Close', 'Volume', 'Close time',
            'Quote asset volume', 'Number of trades', 'Taker buy base asset volume',
            'Taker buy quote asset volume', 'Ignore'
        ])
        
        # Приводим к нужным типам данных
        df['Open time'] = pd.to_datetime(df['Open time'], unit='ms')
        df.set_index('Open time', inplace=True)
        for col in ['Open', 'High', 'Low', 'Close', 'Volume']:
            df[col] = pd.to_numeric(df[col])
            
        # Возвращаем только нужные колонки
        return df[['Open', 'High', 'Low', 'Close', 'Volume']]

    @retry_network_sensitive()
    def place_oco_order(self, symbol: str, side: str, quantity: float,
                        price: float, stop_price: float, stop_limit_price: float) -> str:
        logger.info(f"Размещение OCO ордера: {symbol}, {side}, qty={quantity}")
        result = self.client.create_oco_order(
            symbol=symbol, side=side, quantity=quantity,
            price=price, stopPrice=stop_price,
            stopLimitPrice=stop_limit_price, stopLimitTimeInForce='GTC'
        )
        order_id = str(result['orderListId'])
        logger.info(f"OCO ордер создан с ID: {order_id}")
        return order_id

    @retry_safe_operations()
    def get_order_status(self, symbol: str, order_id: str) -> Dict[str, Any]:
        logger.info(f"Запрос статуса ордера {order_id} для {symbol}")
        return self.client.get_order(symbol=symbol, orderId=int(order_id))

    @retry_network_sensitive()
    def cancel_order(self, symbol: str, order_id: str) -> Dict[str, Any]:
        logger.info(f"Отмена ордера {order_id} для {symbol}")
        result = self.client.cancel_order(symbol=symbol, orderId=int(order_id))
        logger.info(f"Ордер {order_id} отменен, статус: {result.get('status')}")
        return result