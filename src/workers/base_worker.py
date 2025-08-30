"""
Базовый класс для всех воркеров сканирования
"""

import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Set
from datetime import datetime
import structlog

from src.utils.logger import get_component_logger


class BaseWorker(ABC):
    """
    Базовый абстрактный класс для всех воркеров сканирования
    """
    
    def __init__(self, worker_id: int, config: dict):
        """
        Инициализация базового воркера
        
        Args:
            worker_id: Уникальный ID воркера
            config: Конфигурация воркера
        """
        self.worker_id = worker_id
        self.config = config
        self.logger = get_component_logger(f"worker.{self.__class__.__name__}.{worker_id}")
        
        self.is_running = False
        self.task: Optional[asyncio.Task] = None
        
        # Статистика воркера
        self.scan_count = 0
        self.error_count = 0
        self.last_scan_time = None
        self.start_time = None
        
        # Обрабатываемые символы
        self.assigned_symbols: Set[str] = set()
        
    @abstractmethod
    async def scan_symbol(self, symbol: str) -> Optional[Dict]:
        """
        Сканирование одного символа
        
        Args:
            symbol: Торговая пара для сканирования
            
        Returns:
            Результат сканирования или None если ничего не найдено
        """
        pass
    
    @abstractmethod
    async def process_scan_results(self, results: List[Dict]):
        """
        Обработка результатов сканирования
        
        Args:
            results: Список результатов сканирования
        """
        pass
    
    async def start(self):
        """Запуск воркера"""
        if self.is_running:
            self.logger.warning("Worker already running")
            return
        
        self.is_running = True
        self.start_time = datetime.now()
        
        self.logger.info("Starting worker")
        
        # Создаем задачу для основного цикла
        self.task = asyncio.create_task(self._main_loop())
    
    async def stop(self):
        """Остановка воркера"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
        
        self.logger.info(f"Worker stopped - scans: {self.scan_count}, errors: {self.error_count}")
    
    async def _main_loop(self):
        """Основной цикл воркера"""
        try:
            while self.is_running:
                scan_start = datetime.now()
                
                try:
                    # Получаем символы для сканирования
                    symbols_to_scan = await self.get_symbols_to_scan()
                    
                    if not symbols_to_scan:
                        await asyncio.sleep(1)
                        continue
                    
                    # Сканируем символы
                    results = []
                    for symbol in symbols_to_scan:
                        if not self.is_running:
                            break
                        
                        try:
                            result = await self.scan_symbol(symbol)
                            if result:
                                results.append(result)
                        
                        except Exception as e:
                            self.error_count += 1
                            self.logger.error(f"Error scanning symbol {symbol}: {str(e)}")
                    
                    # Обрабатываем результаты
                    if results:
                        await self.process_scan_results(results)
                    
                    self.scan_count += 1
                    self.last_scan_time = datetime.now()
                    
                    # Логируем статистику периодически
                    if self.scan_count % 100 == 0:
                        self.logger.info(f"Worker statistics - scans: {self.scan_count}, errors: {self.error_count}, symbols: {len(symbols_to_scan)}, results: {len(results)}")
                
                except Exception as e:
                    self.error_count += 1
                    self.logger.error(f"Error in main loop: {str(e)}")
                
                # Применяем интервал сканирования
                scan_duration = (datetime.now() - scan_start).total_seconds()
                scan_interval = self.config.get("scan_interval", 1.0)
                
                if scan_duration < scan_interval:
                    await asyncio.sleep(scan_interval - scan_duration)
                    
        except asyncio.CancelledError:
            self.logger.info("Worker cancelled")
            raise
        except Exception as e:
            self.logger.error(f"Fatal error in worker: {str(e)}")
            raise
    
    async def get_symbols_to_scan(self) -> List[str]:
        """
        Получить список символов для сканирования
        
        Returns:
            Список символов для обработки этим воркером
        """
        return list(self.assigned_symbols)
    
    def assign_symbols(self, symbols: List[str]):
        """
        Назначить символы для обработки
        
        Args:
            symbols: Список символов для назначения
        """
        self.assigned_symbols = set(symbols)
        self.logger.debug(f"Assigned {len(symbols)} symbols")
    
    def add_symbol(self, symbol: str):
        """
        Добавить символ для обработки
        
        Args:
            symbol: Символ для добавления
        """
        self.assigned_symbols.add(symbol)
        self.logger.debug(f"Added symbol: {symbol}")
    
    def remove_symbol(self, symbol: str):
        """
        Удалить символ из обработки
        
        Args:
            symbol: Символ для удаления
        """
        self.assigned_symbols.discard(symbol)
        self.logger.debug(f"Removed symbol: {symbol}")
    
    def get_stats(self) -> Dict:
        """
        Получить статистику воркера
        
        Returns:
            Словарь со статистикой
        """
        uptime = None
        if self.start_time:
            uptime = (datetime.now() - self.start_time).total_seconds()
        
        return {
            "worker_id": self.worker_id,
            "is_running": self.is_running,
            "scan_count": self.scan_count,
            "error_count": self.error_count,
            "error_rate": self.error_count / max(self.scan_count, 1),
            "assigned_symbols_count": len(self.assigned_symbols),
            "last_scan_time": self.last_scan_time.isoformat() if self.last_scan_time else None,
            "uptime_seconds": uptime
        }
    
    def __repr__(self) -> str:
        return (f"<{self.__class__.__name__}(id={self.worker_id}, "
                f"running={self.is_running}, symbols={len(self.assigned_symbols)})>")
