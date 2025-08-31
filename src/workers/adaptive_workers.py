"""
Модуль для адаптивного управления воркерами
"""

import asyncio
from typing import List, Dict, Type, Optional
from datetime import datetime

from src.workers.base_worker import BaseWorker
from src.utils.logger import get_component_logger

logger = get_component_logger("adaptive_workers")


class AdaptiveWorkerManager:
    """
    Менеджер для адаптивного управления количеством воркеров
    """
    
    def __init__(self, worker_class: Type[BaseWorker], config: dict):
        """
        Инициализация менеджера воркеров
        
        Args:
            worker_class: Класс воркера для создания экземпляров
            config: Конфигурация воркеров
        """
        self.worker_class = worker_class
        self.config = config
        self.logger = logger
        
        self.workers: List[BaseWorker] = []
        self.next_worker_id = 1
        self.is_running = False
        
        # Параметры адаптации
        self.adaptive_rules = config.get("adaptive_workers", {})
        self.max_workers = config.get("max_workers", 10)
        self.min_workers = config.get("min_workers", 1)
        
    async def start(self):
        """Запуск менеджера воркеров"""
        if self.is_running:
            return
        
        self.is_running = True
        
        # Создаем минимальное количество воркеров
        await self.scale_to(self.min_workers)
        
        self.logger.info(f"Adaptive worker manager started with {len(self.workers)} initial workers")
    
    async def stop(self):
        """Остановка всех воркеров"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # Останавливаем всех воркеров
        tasks = [worker.stop() for worker in self.workers]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        self.workers.clear()
        self.logger.info("All workers stopped")
    
    async def scale_based_on_load(self, current_load_count: int):
        """
        Масштабирование воркеров на основе текущей нагрузки
        
        Args:
            current_load_count: Количество элементов для обработки
        """
        if not self.is_running:
            return
        
        target_workers = self._calculate_required_workers(current_load_count)
        current_workers = len(self.workers)
        
        if target_workers != current_workers:
            self.logger.info(f"Scaling workers: {current_workers} -> {target_workers} (load: {current_load_count})")
            
            await self.scale_to(target_workers)
    
    def _calculate_required_workers(self, load_count: int) -> int:
        """
        Рассчитать необходимое количество воркеров
        
        Args:
            load_count: Текущая нагрузка
            
        Returns:
            Необходимое количество воркеров
        """
        # Применяем правила адаптации из конфига
        target = self.min_workers
        
        for threshold, workers_count in sorted(self.adaptive_rules.items()):
            if load_count >= threshold:
                target = workers_count
            else:
                break
        
        # Ограничиваем минимумом и максимумом
        target = max(self.min_workers, min(self.max_workers, target))
        
        return target
    
    async def scale_to(self, target_count: int):
        """
        Масштабировать до определенного количества воркеров
        
        Args:
            target_count: Целевое количество воркеров
        """
        current_count = len(self.workers)
        
        if target_count > current_count:
            # Добавляем воркеров
            await self._add_workers(target_count - current_count)
        elif target_count < current_count:
            # Удаляем воркеров
            await self._remove_workers(current_count - target_count)
    
    async def _add_workers(self, count: int):
        """
        Добавить воркеров

        Args:
            count: Количество воркеров для добавления
        """
        new_workers = []

        # Берём exchange из конфига (или передаем явно через config)
        exchange = self.config.get("exchange")
        if exchange is None:
            raise ValueError("Config for worker must include 'exchange' key!")

        for _ in range(count):
            # Создаём копию конфига для воркера
            worker_config = self.config.copy()
            worker_config["exchange"] = exchange  # гарантируем наличие exchange

            worker = self.worker_class(self.next_worker_id, worker_config)
            self.next_worker_id += 1

            await worker.start()
            new_workers.append(worker)

        self.workers.extend(new_workers)
        self.logger.info(f"Added {count} workers (total: {len(self.workers)})")
    
    async def _remove_workers(self, count: int):
        """
        Удалить воркеров
        
        Args:
            count: Количество воркеров для удаления
        """
        if count >= len(self.workers):
            count = len(self.workers) - self.min_workers
        
        workers_to_remove = self.workers[-count:]
        self.workers = self.workers[:-count]
        
        # Останавливаем удаляемых воркеров
        tasks = [worker.stop() for worker in workers_to_remove]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        
        self.logger.info(f"Removed {len(workers_to_remove)} workers (total: {len(self.workers)})")
    
    def distribute_work(self, work_items: List):
        """
        Распределить работу между воркерами
        
        Args:
            work_items: Список элементов для распределения
        """
        if not self.workers or not work_items:
            return
        
        # Простое распределение round-robin
        items_per_worker = len(work_items) // len(self.workers)
        remainder = len(work_items) % len(self.workers)
        
        start_idx = 0
        for i, worker in enumerate(self.workers):
            # Некоторые воркеры получают +1 элемент
            items_count = items_per_worker + (1 if i < remainder else 0)
            end_idx = start_idx + items_count
            
            worker_items = work_items[start_idx:end_idx]
            worker.assign_symbols(worker_items)
            
            start_idx = end_idx
    
    def get_all_stats(self) -> Dict:
        """
        Получить статистику всех воркеров
        
        Returns:
            Словарь со статистикой менеджера и воркеров
        """
        workers_stats = [worker.get_stats() for worker in self.workers]
        
        # Агрегированная статистика
        total_scans = sum(stats["scan_count"] for stats in workers_stats)
        total_errors = sum(stats["error_count"] for stats in workers_stats)
        total_symbols = sum(stats["assigned_symbols_count"] for stats in workers_stats)
        
        return {
            "manager_stats": {
                "is_running": self.is_running,
                "worker_count": len(self.workers),
                "total_scans": total_scans,
                "total_errors": total_errors,
                "total_assigned_symbols": total_symbols,
                "error_rate": total_errors / max(total_scans, 1)
            },
            "workers": workers_stats
        }
    
    def get_active_workers(self) -> List[BaseWorker]:
        """
        Получить список активных воркеров
        
        Returns:
            Список работающих воркеров
        """
        return [worker for worker in self.workers if worker.is_running]
    
    async def restart_failed_workers(self):
        """Перезапуск неработающих воркеров"""
        failed_workers = [worker for worker in self.workers if not worker.is_running]
        
        if not failed_workers:
            return
        
        self.logger.warning(f"Restarting {len(failed_workers)} failed workers")
        
        for worker in failed_workers:
            try:
                await worker.start()
            except Exception as e:
                self.logger.error(f"Failed to restart worker {worker.worker_id}: {str(e)}")
