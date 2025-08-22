#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скриннер больших заявок на Binance Futures с ПЕРСИСТЕНТНЫМ ХРАНЕНИЕМ
Минималистичный но рабочий вариант для поиска заявок 500k+ USD
Ограничения: максимум 3 ордера на покупку и 3 на продажу, расстояние макс 10%
Отслеживание времени жизни ордеров + персистентность между итерациями
"""

import requests
import json
import time
import os
from datetime import datetime
from typing import List, Dict, Tuple
from concurrent.futures import ThreadPoolExecutor

class BinanceBigOrdersScanner:
    def __init__(self):
        self.base_url = "https://fapi.binance.com"
        self.data_file = "big_orders_data.json"
        self.min_order_size_usd = 500000  # Минимальный размер ордера в USD
        self.excluded_symbols = ["BTCUSDT", "ETHUSDT"]  # Исключаем BTC и ETH
        self.request_delay = 0  # Задержка между запросами (соблюдение лимитов)
        self.max_orders_per_side = 3  # Максимум 3 ордера на покупку и 3 на продажу
        self.max_distance_percent = 10.0  # Максимальное расстояние от цены 10%
        self.order_history = {}  # DEPRECATED - больше не используется в новой логике
        self.max_workers = 5  # Количество параллельных воркеров (снижено для retry стабильности)
        self.top_symbols_count = 250  # Количество топ символов по объему торгов (капитализации)
        self.persistent_mode = True  # НОВОЕ: Режим персистентного хранения
        self.price_tolerance = 0.0001  # НОВОЕ: Допустимое изменение цены для считания ордера "тем же" (0.01%)
        self.first_run = True  # НОВОЕ: Флаг первого запуска для однократной очистки
        self.verbose_logs = False  # НОВОЕ: Детальные логи (можно включить для отладки)
        
    def make_request_with_retry(self, url: str, params=None, max_retries: int = 3, timeout: int = 10) -> Dict:
        """Выполняем HTTP запрос с retry логикой для обработки rate limits и временных ошибок"""
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
        
    def filter_top_symbols_by_volume(self, symbols: List[str], all_tickers: Dict[str, Dict], top_count: int = 250) -> List[str]:
        """Фильтруем топ-N символов по объему торгов за 24ч (самые капитализированные пары)"""
        try:
            # Создаем список (символ, объем_торгов) для сортировки
            symbol_volumes = []
            for symbol in symbols:
                ticker_data = all_tickers.get(symbol)
                if ticker_data:
                    # Используем quoteVolume (общий объем в USDT за 24ч) как метрику капитализации
                    volume_24h = float(ticker_data.get('quoteVolume', 0))
                    symbol_volumes.append((symbol, volume_24h))
            
            # Сортируем по объему торгов (по убыванию) и берем топ-N
            symbol_volumes.sort(key=lambda x: x[1], reverse=True)
            top_symbols = [symbol for symbol, volume in symbol_volumes[:top_count]]
            
            if self.verbose_logs:
                print(f"Отфильтровано: {len(symbols)} → {len(top_symbols)} символов (топ-{top_count} по объему торгов)")
                
                # Показываем примеры топ-10 для информации
                if len(symbol_volumes) >= 10:
                    print("Топ-10 по объему торгов:")
                    for i, (symbol, volume) in enumerate(symbol_volumes[:10], 1):
                        volume_millions = volume / 1_000_000  # Конвертируем в миллионы USDT
                        print(f"  {i:2d}. {symbol:12s} - {volume_millions:8.1f}M USDT")
            
            return top_symbols
            
        except Exception as e:
            print(f"Ошибка фильтрации символов по объему: {e}")
            print("Используем все символы без фильтрации")
            return symbols
        
    def get_active_symbols(self) -> List[str]:
        """Получаем список активных фьючерсных символов"""
        try:
            url = f"{self.base_url}/fapi/v1/exchangeInfo"
            data = self.make_request_with_retry(url, timeout=10)
            symbols = []
            
            for symbol_info in data['symbols']:
                symbol = symbol_info['symbol']
                # Только USDT пары в активном статусе
                if (symbol.endswith('USDT') and 
                    symbol_info['status'] == 'TRADING' and
                    symbol not in self.excluded_symbols):
                    symbols.append(symbol)
            
            print(f"Найдено {len(symbols)} активных символов для сканирования")
            return symbols 
            
        except Exception as e:
            print(f"Ошибка получения символов: {e}")
            return []
    
    def get_all_tickers_batch(self) -> Dict[str, Dict]:
        """Получаем 24hr статистику для ВСЕХ символов одним запросом (BATCH ОПТИМИЗАЦИЯ)"""
        try:
            url = f"{self.base_url}/fapi/v1/ticker/24hr"
            # БЕЗ параметра symbol = получаем ВСЕ символы!
            tickers_list = self.make_request_with_retry(url, timeout=10)
            tickers_dict = {ticker['symbol']: ticker for ticker in tickers_list}
            
            if self.verbose_logs:
                print(f"Получены ticker данные для {len(tickers_dict)} символов одним запросом")
            return tickers_dict
            
        except Exception as e:
            print(f"Ошибка получения batch ticker: {e}")
            return {}
    
    def get_symbol_data(self, symbol: str, ticker_data: Dict = None) -> Dict:
        """Получаем полные данные символа: цену, статистику 24ч, свечи для волатильности"""
        try:
            # Используем переданные ticker_data (batch) или делаем fallback запрос
            if ticker_data:
                # BATCH режим: данные уже получены
                current_price = float(ticker_data['lastPrice'])
            else:
                # FALLBACK режим: отдельный запрос (если batch не сработал)
                print(f"  FALLBACK: отдельный ticker запрос для {symbol}")
                ticker_url = f"{self.base_url}/fapi/v1/ticker/24hr"
                ticker_data = self.make_request_with_retry(ticker_url, params={"symbol": symbol}, timeout=5)
                current_price = float(ticker_data['lastPrice'])
            
            # Свечи за последний 1 час для расчета волатильности (оптимизировано)
            klines_url = f"{self.base_url}/fapi/v1/klines"
            klines_params = {
                "symbol": symbol,
                "interval": "5m",
                "limit": 12
            }
            klines_data = self.make_request_with_retry(klines_url, params=klines_params, timeout=5)
            
            return {
                'current_price': current_price,
                'ticker_data': ticker_data,
                'klines_data': klines_data
            }
            
        except Exception as e:
            print(f"Ошибка получения данных для {symbol}: {e}")
            return {}
    
    def get_order_book(self, symbol: str) -> Dict:
        """Получаем стакан ордеров для символа"""
        try:
            url = f"{self.base_url}/fapi/v1/depth"
            params = {
            "symbol": symbol,
            "limit": 500  # Оптимальная глубина стакана (экономия weight)
            }
            return self.make_request_with_retry(url, params=params, timeout=10)
            
        except Exception as e:
            print(f"Ошибка получения стакана для {symbol}: {e}")
            return {}
    
    def calculate_symbol_metrics(self, symbol_data: Dict, order_book: Dict) -> Dict:
        """Рассчитываем метрики символа"""
        if not symbol_data or not order_book:
            return {}
        
        current_price = symbol_data['current_price']
        ticker_data = symbol_data.get('ticker_data', {})
        klines_data = symbol_data.get('klines_data', [])
        
        metrics = {}
        
        # Волатильность за 1 час (средний % изменения за 12 последних 5-минутных свечей)
        if len(klines_data) >= 12:
            hour_changes = []
            for i in range(-12, 0):  # Последние 12 свечей (1 час)
                open_price = float(klines_data[i][1])
                close_price = float(klines_data[i][4])
                if open_price > 0:
                    change_percent = abs((close_price - open_price) / open_price * 100)
                    hour_changes.append(change_percent)
            metrics['volatility_1h'] = sum(hour_changes) / len(hour_changes) if hour_changes else 0
        else:
            metrics['volatility_1h'] = 0
        
        # Отношение текущего объема к среднему
        current_volume = float(ticker_data.get('volume', 0))
        avg_volume = float(ticker_data.get('quoteVolume', 1)) / current_price if current_price > 0 else 1
        metrics['volume_ratio'] = current_volume / avg_volume if avg_volume > 0 else 1
        
        # Изменение цены за 5 минут
        if len(klines_data) >= 1:
            price_5min_ago = float(klines_data[-1][1])  # Open price последней свечи
            metrics['price_movement_5min'] = ((current_price - price_5min_ago) / price_5min_ago * 100) if price_5min_ago > 0 else 0
        else:
            metrics['price_movement_5min'] = 0
        
        # Находится ли цена на круглом уровне (кратно 10, 50, 100)
        price_str = f"{current_price:.10f}".rstrip('0').rstrip('.')
        is_round_level = (
            current_price % 100 == 0 or 
            current_price % 50 == 0 or 
            current_price % 10 == 0 or
            price_str.endswith('0') or
            price_str.endswith('00') or
            price_str.endswith('5')
        )
        metrics['is_round_level'] = is_round_level
        
        return metrics
    
    def find_big_orders(self, symbol: str, order_book: Dict, symbol_data: Dict, symbol_metrics: Dict) -> List[Dict]:
        """Находим большие ордера в стакане (максимум 3 с каждой стороны)"""
        big_orders = []
        
        if not order_book or not symbol_data:
            return big_orders
        
        current_price = symbol_data['current_price']
        
        # Временные списки для сортировки
        ask_orders = []
        bid_orders = []
        
        # Собираем все ордера для расчета среднего размера
        all_order_sizes = []
        for ask in order_book.get('asks', []):
            all_order_sizes.append(float(ask[0]) * float(ask[1]))
        for bid in order_book.get('bids', []):
            all_order_sizes.append(float(bid[0]) * float(bid[1]))
        
        avg_order_size = sum(all_order_sizes) / len(all_order_sizes) if all_order_sizes else 1
        
        # Обрабатываем аски (продажи)
        for ask in order_book.get('asks', []):
            price = float(ask[0])
            quantity = float(ask[1])
            usd_value = price * quantity
            
            if usd_value >= self.min_order_size_usd:
                distance_percent = ((price - current_price) / current_price) * 100
                
                # Пропускаем ордера дальше 10% от цены
                if abs(distance_percent) > self.max_distance_percent:
                    continue
                
                # Количество ордеров в радиусе ±0.1% от цены
                price_range_low = price * 0.999
                price_range_high = price * 1.001
                orders_around_count = 0
                for other_ask in order_book.get('asks', []):
                    other_price = float(other_ask[0])
                    if price_range_low <= other_price <= price_range_high:
                        orders_around_count += 1
                
                ask_orders.append({
                    'symbol': symbol,
                    'type': 'ASK',
                    'price': price,
                    'quantity': quantity,
                    'usd_value': usd_value,
                    'distance_percent': distance_percent,
                    'size_vs_average': usd_value / avg_order_size if avg_order_size > 0 else 1,
                    'orders_around_price': orders_around_count,
                    'timestamp': datetime.now().isoformat()
                })
        
        # Обрабатываем биды (покупки)
        for bid in order_book.get('bids', []):
            price = float(bid[0])
            quantity = float(bid[1])
            usd_value = price * quantity
            
            if usd_value >= self.min_order_size_usd:
                distance_percent = ((price - current_price) / current_price) * 100
                
                # Пропускаем ордера дальше 10% от цены
                if abs(distance_percent) > self.max_distance_percent:
                    continue
                
                # Количество ордеров в радиусе ±0.1% от цены
                price_range_low = price * 0.999
                price_range_high = price * 1.001
                orders_around_count = 0
                for other_bid in order_book.get('bids', []):
                    other_price = float(other_bid[0])
                    if price_range_low <= other_price <= price_range_high:
                        orders_around_count += 1
                
                bid_orders.append({
                    'symbol': symbol,
                    'type': 'BID',
                    'price': price,
                    'quantity': quantity,
                    'usd_value': usd_value,
                    'distance_percent': distance_percent,
                    'size_vs_average': usd_value / avg_order_size if avg_order_size > 0 else 1,
                    'orders_around_price': orders_around_count,
                    'timestamp': datetime.now().isoformat()
                })
        
        # Сортируем и берем топ-N самых больших ордеров с каждой стороны
        # ASK: сортируем по размеру (самые большие сначала)
        ask_orders.sort(key=lambda x: x['usd_value'], reverse=True)
        for i, order in enumerate(ask_orders[:self.max_orders_per_side]):
            order['rank_in_side'] = i + 1
            big_orders.append(order)
        
        # BID: сортируем по размеру (самые большие сначала) 
        bid_orders.sort(key=lambda x: x['usd_value'], reverse=True)
        for i, order in enumerate(bid_orders[:self.max_orders_per_side]):
            order['rank_in_side'] = i + 1
            big_orders.append(order)
        
        return big_orders
    
    # ======== НОВЫЕ МЕТОДЫ ДЛЯ ПЕРСИСТЕНТНОГО ХРАНЕНИЯ ========
    
    def create_order_key(self, order: Dict) -> str:
        """Создаем уникальный ключ для ордера"""
        return f"{order['symbol']}-{order['type']}-{order['price']:.8f}-{order['quantity']:.8f}"
    
    def orders_are_same(self, order1: Dict, order2: Dict) -> bool:
        """Проверяем, один ли это ордер (с учетом небольших изменений цены/количества)"""
        if (order1['symbol'] != order2['symbol'] or 
            order1['type'] != order2['type']):
            return False
        
        # Проверяем разницу в цене и количестве (в процентах)
        price_diff = abs(order1['price'] - order2['price']) / order1['price'] if order1['price'] > 0 else 1
        quantity_diff = abs(order1['quantity'] - order2['quantity']) / order1['quantity'] if order1['quantity'] > 0 else 1
        
        # Ордеры считаются одинаковыми, если разница меньше допустимой
        return price_diff <= self.price_tolerance and quantity_diff <= self.price_tolerance
    
    def load_existing_data(self) -> List[Dict]:
        """Загружаем существующие данные"""
        if not os.path.exists(self.data_file):
            return []
        
        try:
            with open(self.data_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Ошибка чтения существующих данных: {e}")
            return []
    
    def merge_orders_data(self, new_symbol_data: Dict) -> Dict:
        """Объединяем новые данные с существующими без потери истории"""
        existing_data = self.load_existing_data()
        current_time = datetime.now().isoformat()
        
        # Находим существующий символ
        existing_symbol_data = None
        for data in existing_data:
            if data['symbol'] == new_symbol_data['symbol']:
                existing_symbol_data = data
                break
        
        if not existing_symbol_data:
            # Новый символ - помечаем все ордера как новые
            for order in new_symbol_data['orders']:
                order['first_seen'] = current_time
                order['last_seen'] = current_time  
                order['is_persistent'] = False
                order['scan_count'] = 1
                order['lifetime_minutes'] = 0
            return new_symbol_data
        
        # Обрабатываем существующие и новые ордера
        merged_orders = []
        new_orders = new_symbol_data['orders']
        existing_orders = existing_symbol_data.get('orders', [])
        
        # Помечаем какие ордера найдены в новом скане
        found_existing_orders = set()
        persistent_orders_log = []  # НОВОЕ: для логирования персистентных ордеров
        
        # Обрабатываем новые ордера
        for new_order in new_orders:
            matched_existing = None
            
            # Ищем соответствующий существующий ордер
            for i, existing_order in enumerate(existing_orders):
                if self.orders_are_same(new_order, existing_order):
                    matched_existing = existing_order
                    found_existing_orders.add(i)
                    break
            
            if matched_existing:
                # Существующий ордер - обновляем
                updated_order = new_order.copy()
                updated_order['first_seen'] = matched_existing.get('first_seen', current_time)
                updated_order['last_seen'] = current_time
                updated_order['is_persistent'] = True
                updated_order['scan_count'] = matched_existing.get('scan_count', 0) + 1
                
                # Вычисляем время жизни
                try:
                    first_time = datetime.fromisoformat(matched_existing.get('first_seen', current_time))
                    current_time_dt = datetime.fromisoformat(current_time)
                    lifetime_minutes = (current_time_dt - first_time).total_seconds() / 60
                    updated_order['lifetime_minutes'] = round(lifetime_minutes, 1)
                    
                    # НОВОЕ: Логирование персистентных ордеров
                    order_info = f"{updated_order['type']} ${updated_order['usd_value']:,.0f} @ {updated_order['price']:.4f}"
                    persistent_orders_log.append(f"  🔄 {order_info} (живет {lifetime_minutes:.1f}мин, скан #{updated_order['scan_count']})")
                    
                except:
                    updated_order['lifetime_minutes'] = 0
                
                merged_orders.append(updated_order)
            else:
                # Новый ордер
                new_order['first_seen'] = current_time
                new_order['last_seen'] = current_time
                new_order['is_persistent'] = False  
                new_order['scan_count'] = 1
                new_order['lifetime_minutes'] = 0
                merged_orders.append(new_order)
        
        # Логирование персистентных ордеров
        if persistent_orders_log:
            print(f"🔍 {new_symbol_data['symbol']}: Найдены персистентные ордера:")
            for log_line in persistent_orders_log:
                print(log_line)
        
        # НЕ добавляем ордера, которые исчезли (они автоматически удаляются)
        
        new_symbol_data['orders'] = merged_orders
        return new_symbol_data
    
    def update_data_file(self, updated_symbol_data: Dict):
        """Обновляем данные конкретного символа в файле"""
        all_data = self.load_existing_data()
        
        # Находим и заменяем данные символа
        symbol_found = False
        for i, data in enumerate(all_data):
            if data['symbol'] == updated_symbol_data['symbol']:
                all_data[i] = updated_symbol_data
                symbol_found = True
                break
        
        # Если символа не было, добавляем
        if not symbol_found:
            all_data.append(updated_symbol_data)
        
        # Сохраняем
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
            
            # Компактное логирование обновлений
            new_orders = [o for o in updated_symbol_data['orders'] if not o.get('is_persistent', False)]
            persistent_orders = [o for o in updated_symbol_data['orders'] if o.get('is_persistent', False)]
            
            if new_orders or self.verbose_logs:
                status_parts = []
                if new_orders:
                    status_parts.append(f"{len(new_orders)} новых")
                if persistent_orders:
                    status_parts.append(f"{len(persistent_orders)} перс.")
                
                status = ", ".join(status_parts) if status_parts else "0 ордеров"
                symbol_log = f"✅ {updated_symbol_data['symbol']}: {status}"
                
                # Только в вербозном режиме или если есть новые ордера
                if new_orders or self.verbose_logs:
                    print(symbol_log)
            
        except Exception as e:
            print(f"Ошибка сохранения: {e}")
    
    def remove_symbol_from_data(self, symbol: str):
        """Удаляем символ из данных (если больше нет больших ордеров)"""
        all_data = self.load_existing_data()
        original_count = len(all_data)
        all_data = [data for data in all_data if data['symbol'] != symbol]
        
        if len(all_data) < original_count:
            try:
                with open(self.data_file, 'w', encoding='utf-8') as f:
                    json.dump(all_data, f, ensure_ascii=False, indent=2)
                print(f"  Удален {symbol} (нет больших ордеров)")
            except Exception as e:
                print(f"Ошибка удаления символа: {e}")
    
    # ======== КОНЕЦ НОВЫХ МЕТОДОВ ========
    
    def clear_data_file(self):
        """Очищаем файл с данными"""
        try:
            if os.path.exists(self.data_file):
                os.remove(self.data_file)
            print("Старые данные очищены")
        except Exception as e:
            print(f"Ошибка очистки файла: {e}")
    
    def save_symbol_data_persistent(self, symbol: str, symbol_data: Dict, symbol_metrics: Dict, big_orders: List[Dict]):
        """Сохраняем данные с сохранением истории (НОВАЯ ЛОГИКА)"""
        if not big_orders:
            # Даже если нет больших ордеров, нужно обновить существующие данные
            # (удалить ордера, которых больше нет)
            self.remove_symbol_from_data(symbol)
            return
        
        # Создаем объект символа
        symbol_object = {
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'current_price': symbol_data.get('current_price', 0),
            'volatility_1h': symbol_metrics.get('volatility_1h', 0),
            'volume_ratio': symbol_metrics.get('volume_ratio', 0), 
            'price_movement_5min': symbol_metrics.get('price_movement_5min', 0),
            'is_round_level': symbol_metrics.get('is_round_level', False),
            'orders_count': len(big_orders),
            'orders': big_orders
        }
        
        # Объединяем с существующими данными
        merged_symbol_data = self.merge_orders_data(symbol_object)
        
        # Сохраняем обновленные данные
        self.update_data_file(merged_symbol_data)
    
    def save_symbol_data(self, symbol: str, symbol_data: Dict, symbol_metrics: Dict, big_orders: List[Dict]):
        """Обертка для совместимости - выбираем старую или новую логику"""
        if self.persistent_mode:
            self.save_symbol_data_persistent(symbol, symbol_data, symbol_metrics, big_orders)
        else:
            # Старая логика (для обратной совместимости)
            self.save_symbol_data_old_logic(symbol, symbol_data, symbol_metrics, big_orders)
    
    def save_symbol_data_old_logic(self, symbol: str, symbol_data: Dict, symbol_metrics: Dict, big_orders: List[Dict]):
        """СТАРАЯ логика сохранения (для обратной совместимости)"""
        if not big_orders:
            return
        
        # Обрабатываем каждый ордер для отслеживания повторов
        processed_orders = []
        for order in big_orders:
            # Создаем уникальный ключ для ордера
            order_key = f"{order['symbol']}-{order['type']}-{order['price']}-{order['quantity']}"
            
            # Проверяем, был ли уже такой ордер
            if order_key in self.order_history:
                self.order_history[order_key] += 1
            else:
                self.order_history[order_key] = 1
            
            # Добавляем счетчик в ордер
            order['count'] = self.order_history[order_key]
            processed_orders.append(order)
        
        # Создаем объект для символа
        symbol_object = {
            'symbol': symbol,
            'timestamp': datetime.now().isoformat(),
            'current_price': symbol_data.get('current_price', 0),
            'volatility_1h': symbol_metrics.get('volatility_1h', 0),
            'volume_ratio': symbol_metrics.get('volume_ratio', 0),
            'price_movement_5min': symbol_metrics.get('price_movement_5min', 0),
            'is_round_level': symbol_metrics.get('is_round_level', False),
            'orders_count': len(processed_orders),
            'orders': processed_orders
        }
        
        # Читаем существующие данные или создаем новые
        all_data = []
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    all_data = json.load(f)
            except:
                all_data = []
        
        # Добавляем новые данные
        all_data.append(symbol_object)
        
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(all_data, f, ensure_ascii=False, indent=2)
            
            print(f"Сохранено {len(processed_orders)} ордеров для {symbol}")
            
        except Exception as e:
            print(f"Ошибка сохранения данных: {e}")
    
    def process_symbol_with_index(self, symbol_task: tuple) -> int:
        """Обрабатываем один символ с индексом (и batch ticker данными)"""
        symbol, index, total, ticker_data = symbol_task  # Теперь тупл 4 элемента
        try:
            if self.verbose_logs:
                print(f"Сканирование {symbol} ({index}/{total})")
            
            # Получаем полные данные символа (используя batch ticker)
            symbol_data = self.get_symbol_data(symbol, ticker_data)
            if not symbol_data:
                return 0
            
            # Получаем стакан ордеров
            order_book = self.get_order_book(symbol)
            if not order_book:
                return 0
            
            # Рассчитываем метрики символа
            symbol_metrics = self.calculate_symbol_metrics(symbol_data, order_book)
            
            # Ищем большие ордера
            big_orders = self.find_big_orders(symbol, order_book, symbol_data, symbol_metrics)
            
            if big_orders:
                # Логирование новых ордеров (компактно)
                total_usd = sum(order['usd_value'] for order in big_orders)
                print(f"💰 {symbol}: {len(big_orders)} ордеров (${total_usd:,.0f})")
                
                self.save_symbol_data(symbol, symbol_data, symbol_metrics, big_orders)
                return len(big_orders)
            
            return 0
            
        except Exception as e:
            print(f"Ошибка обработки {symbol}: {e}")
            return 0
    
    def scan_all_symbols(self):
        """Основной метод сканирования топ-250 символов с BATCH оптимизацией и ПЕРСИСТЕНТНЫМ ХРАНЕНИЕМ"""
        mode_text = "ПЕРСИСТЕНТНЫМ" if self.persistent_mode else "ОБЫЧНЫМ"
        
        if self.first_run:
            print(f"🚀 Начало сканирования в {mode_text} режиме ({self.max_workers} воркеров)")
            
            # Очищаем файл ТОЛЬКО при первом запуске
            if not self.persistent_mode:
                self.clear_data_file()
                print("🗑️ Очищены старые данные (обычный режим)")
            else:
                print("💾 Персистентный режим: сохраняем существующие данные")
            
            self.first_run = False  # Отмечаем, что первый запуск завершен
        else:
            # Последующие итерации - компактное логирование
            print(f"🔄 Новая итерация...")
        
        # Получаем список активных символов
        symbols = self.get_active_symbols()
        if not symbols:
            print("Не удалось получить список символов")
            return
        
        # КЛЮЧЕВОЕ: Получаем ВСЕ ticker данные одним запросом!
        if self.verbose_logs:
            print("Получаем ВСЕ ticker данные одним batch запросом...")
        all_tickers = self.get_all_tickers_batch()
        if not all_tickers:
            print("Ошибка получения batch ticker! Отменяем сканирование.")
            return
        
        # НОВОЕ: Фильтруем только топ-N символов по объему торгов (капитализации)
        if self.verbose_logs:
            print(f"Фильтруем топ-{self.top_symbols_count} символов по объему торгов...")
        filtered_symbols = self.filter_top_symbols_by_volume(symbols, all_tickers, top_count=self.top_symbols_count)
        
        total_big_orders = 0
        
        # Создаем кортежи (символ, индекс, общее_количество, ticker_data) для отфильтрованных символов
        symbol_tasks = []
        for i, symbol in enumerate(filtered_symbols):
            ticker_data = all_tickers.get(symbol)  # Получаем ticker данные для символа
            if ticker_data:  # Обрабатываем только символы с ticker данными
                symbol_tasks.append((symbol, i+1, len(filtered_symbols), ticker_data))
        
        print(f"🚀 Обрабатываем {len(symbol_tasks)} символов...")
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            results = executor.map(self.process_symbol_with_index, symbol_tasks)
            for result in results:
                total_big_orders += result
        
        print(f"\n🏁 Сканирование завершено! Всего найдено {total_big_orders} больших ордеров")
        if self.verbose_logs:
            print(f"Данные сохранены в файл: {self.data_file}")
    
    def continuous_scan(self):
        """Непрерывное сканирование без задержки"""
        print(f"Запуск непрерывного сканирования (без пауз между итерациями)")
        
        iteration = 1
        while True:
            try:
                print(f"\n--- Итерация {iteration} ---")
                self.scan_all_symbols()
                iteration += 1
                
            except KeyboardInterrupt:
                print("\nОстановка сканирования по запросу пользователя")
                break
            except Exception as e:
                print(f"Ошибка в процессе сканирования: {e}")
                print("Повторная попытка через 30 секунд...")
                time.sleep(30)

def main():
    """Главная функция"""
    scanner = BinanceBigOrdersScanner()
    
    print("=== СКРИННЕР БОЛЬШИХ ЗАЯВОК BINANCE FUTURES (С ПЕРСИСТЕНТНЫМ ХРАНЕНИЕМ) ===")
    print("Минимальный размер ордера: $500,000")
    print("Исключенные символы: BTC, ETH")
    print("Ограничения: макс 3+3 ордера/символ, макс 10% от цены")
    print(f"🔥 НОВОЕ: Персистентное хранение данных - режим {'ВКЛЮЧЕН' if scanner.persistent_mode else 'ВЫКЛЮЧЕН'}")
    if scanner.persistent_mode:
        print("✅ Отслеживание времени жизни ордеров (first_seen, last_seen, lifetime_minutes)")
        print("✅ Различение новых и существующих ордеров (is_persistent, scan_count)")
        print("✅ Сохранение данных между итерациями (ордера не стираются)")
        print("✅ Автоматическое удаление исчезнувших ордеров")
        print("🔍 Логирование персистентных ордеров с временем жизни")
    print(f"Фильтрация: только топ-{scanner.top_symbols_count} пар по объему торгов (самые капитализированные)")
    print("Дополнительные метрики: volatility_1h, volume_ratio, rank_in_side, size_vs_average")
    print("Вывод: JSON объекты с массивом ордеров")
    print(f"Параллельные запросы: {scanner.max_workers} воркеров")
    print(f"ОПТИМИЗАЦИИ: BATCH ticker запросы (1 вместо 471+), топ-{scanner.top_symbols_count} по капитализации, стакан 500")
    print("НАДЕЖНОСТЬ: Retry логика для 429/5xx ошибок, экспоненциальные задержки")
    print(f"🔍 Режим логов: {'ВЕРБОЗНЫЙ' if scanner.verbose_logs else 'КОМПАКТНЫЙ'}")
    print("=" * 80)
    
    try:
        # Выбор режима работы  
        print("\nВыберите режим работы:")
        print("1 - Одноразовое сканирование (персистентный режим)")
        print("2 - Непрерывное сканирование (персистентный режим)")
        print("3 - Одноразовое сканирование (старый режим - очистка данных)")
        print("4 - Переключить режим персистентности")
        print("5 - Переключить вербозные логи")
        
        choice = input("Введите номер (1-5): ").strip()
        
        if choice == "1":
            scanner.scan_all_symbols()
        elif choice == "2":
            scanner.continuous_scan()
        elif choice == "3":
            print("\n🔄 Переключение в старый режим (с очисткой данных)...")
            scanner.persistent_mode = False
            scanner.first_run = True  # Сбрасываем флаг для очистки
            scanner.scan_all_symbols()
        elif choice == "4":
            current_mode = "ПЕРСИСТЕНТНЫЙ" if scanner.persistent_mode else "ОБЫЧНЫЙ"
            new_mode = "ОБЫЧНЫЙ" if scanner.persistent_mode else "ПЕРСИСТЕНТНЫЙ"
            print(f"\n🔄 Переключение: {current_mode} → {new_mode}")
            scanner.persistent_mode = not scanner.persistent_mode
            scanner.first_run = True  # Сбрасываем флаг при смене режима
            scanner.scan_all_symbols()
        elif choice == "5":
            current_verbose = "ВЕРБОЗНЫЕ" if scanner.verbose_logs else "КОМПАКТНЫЕ"
            new_verbose = "КОМПАКТНЫЕ" if scanner.verbose_logs else "ВЕРБОЗНЫЕ"
            print(f"\n🔊 Переключение логов: {current_verbose} → {new_verbose}")
            scanner.verbose_logs = not scanner.verbose_logs
            scanner.scan_all_symbols()
        else:
            print("Неверный выбор. Запуск одноразового сканирования в персистентном режиме...")
            scanner.scan_all_symbols()
            
    except KeyboardInterrupt:
        print("\nПрограмма остановлена пользователем")
    except Exception as e:
        print(f"Критическая ошибка: {e}")

if __name__ == "__main__":
    main()
