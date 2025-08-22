#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Скриннер больших заявок на Binance Futures
Минималистичный но рабочий вариант для поиска заявок 500k+ USD
Ограничения: максимум 3 ордера на покупку и 3 на продажу, расстояние макс 10%
Отслеживание повторяющихся ордеров со счетчиком
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
        self.order_history = {}  # Для отслеживания повторяющихся ордеров
        self.max_workers = 7  # Количество параллельных воркеров
        
    def get_active_symbols(self) -> List[str]:
        """Получаем список активных фьючерсных символов"""
        try:
            url = f"{self.base_url}/fapi/v1/exchangeInfo"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            data = response.json()
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
    
    def get_symbol_data(self, symbol: str) -> Dict:
        """Получаем полные данные символа: цену, статистику 24ч, свечи для волатильности"""
        try:
            # Текущая цена
            price_url = f"{self.base_url}/fapi/v1/ticker/price"
            price_response = requests.get(price_url, params={"symbol": symbol}, timeout=5)
            price_response.raise_for_status()
            current_price = float(price_response.json()['price'])
            
            # 24hr статистика
            ticker_url = f"{self.base_url}/fapi/v1/ticker/24hr"
            ticker_response = requests.get(ticker_url, params={"symbol": symbol}, timeout=5)
            ticker_response.raise_for_status()
            ticker_data = ticker_response.json()
            
            # Свечи за последние 2 часа для расчета волатильности
            klines_url = f"{self.base_url}/fapi/v1/klines"
            klines_params = {
                "symbol": symbol,
                "interval": "5m",
                "limit": 24  # 24 свечи по 5 минут = 2 часа
            }
            klines_response = requests.get(klines_url, params=klines_params, timeout=5)
            klines_response.raise_for_status()
            klines_data = klines_response.json()
            
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
                "limit": 1000  # Максимальная глубина стакана
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            
            return response.json()
            
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
    
    def clear_data_file(self):
        """Очищаем файл с данными"""
        try:
            if os.path.exists(self.data_file):
                os.remove(self.data_file)
            print("Старые данные очищены")
        except Exception as e:
            print(f"Ошибка очистки файла: {e}")
    
    def save_symbol_data(self, symbol: str, symbol_data: Dict, symbol_metrics: Dict, big_orders: List[Dict]):
        """Сохраняем данные символа в JSON формате"""
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
        """Обрабатываем один символ с индексом"""
        symbol, index, total = symbol_task
        try:
            print(f"Сканирование {symbol} ({index}/{total})")
            
            # Получаем полные данные символа
            symbol_data = self.get_symbol_data(symbol)
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
                print(f"  Найдено {len(big_orders)} больших ордеров в {symbol} (топ-3 с каждой стороны)")
                self.save_symbol_data(symbol, symbol_data, symbol_metrics, big_orders)
                return len(big_orders)
            
            return 0
            
        except Exception as e:
            print(f"Ошибка обработки {symbol}: {e}")
            return 0
    
    def scan_all_symbols(self):
        """Основной метод сканирования всех символов с параллельными запросами"""
        print(f"Запуск сканирования больших ордеров ({self.max_workers} воркеров)...")
        
        # Очищаем старые данные при каждом запуске
        self.clear_data_file()
        
        symbols = self.get_active_symbols()
        if not symbols:
            print("Не удалось получить список символов")
            return
        
        total_big_orders = 0
        
        # Создаем кортежи (символ, индекс, общее_количество)
        symbol_tasks = [(symbol, i+1, len(symbols)) for i, symbol in enumerate(symbols)]
        
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            results = executor.map(self.process_symbol_with_index, symbol_tasks)
            for result in results:
                total_big_orders += result
        
        print(f"\nСканирование завершено! Всего найдено {total_big_orders} больших ордеров")
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
    
    print("=== СКРИННЕР БОЛЬШИХ ЗАЯВОК BINANCE FUTURES ===")
    print("Минимальный размер ордера: $500,000")
    print("Исключенные символы: BTC, ETH")
    print("Ограничения: макс 3+3 ордера/символ, макс 10% от цены")
    print("Отслеживание повторов со счетчиком")
    print("Дополнительные метрики: volatility_1h, volume_ratio, rank_in_side, size_vs_average")
    print("Вывод: JSON объекты с массивом ордеров")
    print(f"Параллельные запросы: {scanner.max_workers} воркеров")
    print("=" * 50)
    
    try:
        # Выбор режима работы
        print("\nВыберите режим работы:")
        print("1 - Одноразовое сканирование")
        print("2 - Непрерывное сканирование (без пауз)")
        
        choice = input("Введите номер (1 или 2): ").strip()
        
        if choice == "1":
            scanner.scan_all_symbols()
        elif choice == "2":
            scanner.continuous_scan()
        else:
            print("Неверный выбор. Запуск одноразового сканирования...")
            scanner.scan_all_symbols()
            
    except KeyboardInterrupt:
        print("\nПрограмма остановлена пользователем")
    except Exception as e:
        print(f"Критическая ошибка: {e}")

if __name__ == "__main__":
    main()
