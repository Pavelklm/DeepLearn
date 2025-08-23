#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
HTTP клиент для работы с Binance API с retry логикой
"""

import requests
import time
from typing import Dict, Optional

try:
    from config import ScannerConfig
except ImportError:
    from .config import ScannerConfig


class BinanceAPIClient:
    """HTTP клиент для Binance API с обработкой ошибок"""
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or ScannerConfig.BASE_URL
        self.timeout = ScannerConfig.REQUEST_TIMEOUT
        self.max_retries = ScannerConfig.MAX_RETRIES
        
    def make_request_with_retry(self, url: str, params: Optional[Dict] = None, 
                              max_retries: int = None, timeout: int = None) -> Dict:
        """Выполняем HTTP запрос с retry логикой для обработки rate limits и временных ошибок"""
        max_retries = max_retries or ScannerConfig.MAX_RETRIES
        timeout = timeout or ScannerConfig.REQUEST_TIMEOUT
        
        for attempt in range(max_retries + 1):  # +1 чтобы включить изначальную попытку
            try:
                response = requests.get(url, params=params, timeout=timeout)
                
                # Обработка rate limiting (429)
                if response.status_code == 429:
                    retry_after = int(response.headers.get('Retry-After', 60))  # Default 60 сек
                    if attempt < max_retries:
                        print(f"  Rate limit (429): ждем {retry_after} сек, попытка {attempt + 1}/{max_retries + 1}")
                        time.sleep(retry_after)
                        continue
                    else:
                        print(f"  Rate limit: превышено максимальное количество попыток")
                        response.raise_for_status()
                
                # Обработка серверных ошибок (5xx)
                elif 500 <= response.status_code < 600:
                    if attempt < max_retries:
                        delay = (2 ** attempt)  # Экспоненциальная задержка: 1, 2, 4 сек
                        print(f"  Серверная ошибка {response.status_code}: повтор через {delay} сек, попытка {attempt + 1}/{max_retries + 1}")
                        time.sleep(delay)
                        continue
                    else:
                        response.raise_for_status()
                
                # Успешный ответ
                response.raise_for_status()
                return response.json()
                
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                if attempt < max_retries:
                    delay = (2 ** attempt)  # Экспоненциальная задержка
                    print(f"  Сетевая ошибка ({type(e).__name__}): повтор через {delay} сек, попытка {attempt + 1}/{max_retries + 1}")
                    time.sleep(delay)
                    continue
                else:
                    print(f"  Сетевая ошибка: превышено максимальное количество попыток")
                    raise e
            
            except requests.exceptions.RequestException as e:
                # Для других ошибок HTTP не повторяем
                print(f"  HTTP ошибка (не повторяется): {e}")
                raise e
        
        # Не должны сюда попасть, но на всякий случай
        raise Exception(f"Неожиданная ошибка после {max_retries + 1} попыток")
    
    def get_exchange_info(self) -> Dict:
        """Получаем информацию о торговых парах"""
        url = f"{self.base_url}/fapi/v1/exchangeInfo"
        return self.make_request_with_retry(url, timeout=10)
    
    def get_all_tickers_24hr(self) -> Dict:
        """Получаем 24hr статистику для ВСЕХ символов одним запросом"""
        url = f"{self.base_url}/fapi/v1/ticker/24hr"
        return self.make_request_with_retry(url, timeout=10)
    
    def get_ticker_24hr(self, symbol: str) -> Dict:
        """Получаем 24hr статистику для конкретного символа"""
        url = f"{self.base_url}/fapi/v1/ticker/24hr"
        params = {"symbol": symbol}
        return self.make_request_with_retry(url, params=params, timeout=5)
    
    def get_klines(self, symbol: str, interval: str = "5m", limit: int = 12) -> Dict:
        """Получаем данные свечей"""
        url = f"{self.base_url}/fapi/v1/klines"
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": limit
        }
        return self.make_request_with_retry(url, params=params, timeout=5)
    
    def get_order_book(self, symbol: str, limit: int = 500) -> Dict:
        """Получаем стакан ордеров"""
        url = f"{self.base_url}/fapi/v1/depth"
        params = {
            "symbol": symbol,
            "limit": limit
        }
        return self.make_request_with_retry(url, params=params, timeout=10)
