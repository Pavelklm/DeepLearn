import sqlite3
from typing import Dict, Any
import logging
import os

logger = logging.getLogger(__name__)

class DatabaseManager:
    def __init__(self, db_path='database/trading_database.db'):
        try:

            db_dir = os.path.dirname(db_path)
            if db_dir and not os.path.exists(db_dir):
                os.makedirs(db_dir)
    
            self.conn = sqlite3.connect(db_path, check_same_thread=False)
            self.create_tables()
        except sqlite3.Error as e:
            logger.error(f"Ошибка подключения к базе данных {db_path}: {e}")
            raise

    def create_tables(self):
        """Создает таблицу для хранения всех сделок, если она не существует."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bot_name TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    entry_price REAL,
                    exit_price REAL,
                    profit REAL,
                    success BOOLEAN,
                    position_size REAL,
                    trade_type TEXT
                )
            ''')
            self.conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Ошибка создания таблицы 'trades': {e}")

    def save_trade(self, bot_name: str, trade_result: Dict[str, Any]):
        """Сохраняет результат закрытой сделки в базу данных."""
        try:
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO trades (bot_name, timestamp, entry_price, exit_price, profit, success, position_size, trade_type)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                bot_name,
                trade_result.get('timestamp'),
                trade_result.get('entry_price'),
                trade_result.get('exit_price'),
                trade_result.get('profit'),
                trade_result.get('success'),
                trade_result.get('position_size_usd'),
                trade_result.get('trade_type')
            ))
            self.conn.commit()
            logger.info(f"Сделка для бота '{bot_name}' успешно сохранена в БД.")
        except sqlite3.Error as e:
            logger.error(f"Ошибка сохранения сделки для бота '{bot_name}': {e}")

    def __del__(self):
        if self.conn:
            self.conn.close()