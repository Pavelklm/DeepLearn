"""
Система мониторинга производительности и здоровья сканнера
"""

import asyncio
import time
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
from pathlib import Path

from src.utils.logger import get_component_logger
from config.main_config import MONITORING_CONFIG

logger = get_component_logger("monitor")


@dataclass
class PerformanceMetrics:
    """Метрики производительности компонента"""
    component_name: str
    timestamp: datetime
    
    # Основные метрики
    uptime_seconds: float = 0.0
    cpu_usage_percent: float = 0.0
    memory_usage_mb: float = 0.0
    
    # Метрики задач
    active_tasks: int = 0
    completed_tasks: int = 0
    failed_tasks: int = 0
    average_task_duration: float = 0.0
    
    # Сетевые метрики  
    api_requests_total: int = 0
    api_requests_failed: int = 0
    api_response_time_avg: float = 0.0
    
    # Специфичные метрики
    custom_metrics: Dict[str, Any] = None
    
    def __post_init__(self):
        if self.custom_metrics is None:
            self.custom_metrics = {}


class SystemMonitor:
    """Центральная система мониторинга всех компонентов"""
    
    def __init__(self):
        self.logger = logger
        self.component_stats: Dict[str, Any] = {}
        
        # Конфигурация
        self.config = MONITORING_CONFIG
        self.check_interval = self.config.get("check_interval", 30)
        
        # Задачи
        self.monitor_task = None
        self.export_task = None
        self.is_running = False
        
        # Экспорт данных
        self.export_enabled = self.config.get("export_enabled", True)
        self.export_file = Path(self.config.get("export_file", "data/monitoring.json"))
        self.export_file.parent.mkdir(exist_ok=True)
        
        # Зарегистрированные компоненты
        self.registered_components: Dict[str, Any] = {}
    
    def register_component(self, name: str, component: Any):
        """Регистрация компонента для мониторинга"""
        self.registered_components[name] = component
        self.logger.info("Component registered for monitoring", component=name)
    
    def unregister_component(self, name: str):
        """Отмена регистрации компонента"""
        if name in self.registered_components:
            del self.registered_components[name]
            self.logger.info("Component unregistered", component=name)
    
    async def start(self):
        """Запуск системы мониторинга"""
        if self.is_running:
            return
        
        self.is_running = True
        
        # Запускаем основной цикл мониторинга
        self.monitor_task = asyncio.create_task(self._monitoring_loop())
        
        # Запускаем задачу экспорта данных
        if self.export_enabled:
            self.export_task = asyncio.create_task(self._export_loop())
        
        self.logger.info("System monitoring started", 
                        components_count=len(self.registered_components),
                        check_interval=self.check_interval)
    
    async def stop(self):
        """Остановка системы мониторинга"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # Останавливаем задачи
        if self.monitor_task:
            self.monitor_task.cancel()
            try:
                await self.monitor_task
            except asyncio.CancelledError:
                pass
        
        if self.export_task:
            self.export_task.cancel()
            try:
                await self.export_task
            except asyncio.CancelledError:
                pass
        
        # Финальный экспорт данных
        if self.export_enabled:
            await self._export_data()
        
        self.logger.info("System monitoring stopped")
    
    async def _monitoring_loop(self):
        """Основной цикл мониторинга"""
        while self.is_running:
            try:
                await self._collect_all_metrics()
                await asyncio.sleep(self.check_interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in monitoring loop", error=str(e))
                await asyncio.sleep(5)
    
    async def _collect_all_metrics(self):
        """Сбор метрик со всех компонентов"""
        timestamp = datetime.now(timezone.utc)
        
        for name, component in self.registered_components.items():
            try:
                if hasattr(component, 'get_stats'):
                    stats = component.get_stats()
                    
                    self.component_stats[name] = {
                        'timestamp': timestamp.isoformat(),
                        'stats': stats,
                        'health_status': self._assess_health(name, stats)
                    }
                    
            except Exception as e:
                self.logger.warning("Error collecting metrics", 
                                  component=name, error=str(e))
                self.component_stats[name] = {
                    'timestamp': timestamp.isoformat(),
                    'error': str(e),
                    'health_status': 'error'
                }
    
    def _assess_health(self, component_name: str, stats: Dict) -> str:
        """Оценка здоровья компонента"""
        try:
            # Базовые проверки
            if not stats.get('is_running', True):
                return 'critical'
            
            # Проверка error rate
            total_requests = stats.get('total_requests', 0)
            error_count = stats.get('error_count', 0)
            
            if total_requests > 0:
                error_rate = error_count / total_requests
                if error_rate > 0.1:  # 10% ошибок
                    return 'warning'
                elif error_rate > 0.2:  # 20% ошибок
                    return 'critical'
            
            # Проверка времени отклика
            response_time = stats.get('avg_response_time', 0)
            if response_time > 5:  # 5 секунд
                return 'warning'
            elif response_time > 10:  # 10 секунд
                return 'critical'
            
            return 'healthy'
            
        except Exception:
            return 'unknown'
    
    async def _export_loop(self):
        """Цикл экспорта данных мониторинга"""
        export_interval = self.config.get("export_interval", 300)  # 5 минут
        
        while self.is_running:
            try:
                await asyncio.sleep(export_interval)
                await self._export_data()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in export loop", error=str(e))
    
    async def _export_data(self):
        """Экспорт данных мониторинга в файл"""
        try:
            export_data = {
                'timestamp': datetime.now(timezone.utc).isoformat(),
                'system_overview': self.get_system_overview(),
                'components': self.component_stats.copy()
            }
            
            # Атомарная запись в файл
            temp_file = self.export_file.with_suffix('.tmp')
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=2, ensure_ascii=False, default=str)
            
            temp_file.replace(self.export_file)
            
            self.logger.debug("Monitoring data exported", 
                            file_size=self.export_file.stat().st_size)
            
        except Exception as e:
            self.logger.error("Error exporting monitoring data", error=str(e))
    
    def get_system_overview(self) -> Dict:
        """Получить обзор состояния всей системы"""
        if not self.component_stats:
            return {'status': 'no_data', 'components_count': 0}
        
        # Собираем статистику по компонентам
        healthy_count = 0
        warning_count = 0
        critical_count = 0
        error_count = 0
        
        for name, data in self.component_stats.items():
            health_status = data.get('health_status', 'unknown')
            
            if health_status == 'healthy':
                healthy_count += 1
            elif health_status == 'warning':
                warning_count += 1
            elif health_status == 'critical':
                critical_count += 1
            else:
                error_count += 1
        
        # Определяем общий статус системы
        total_components = len(self.component_stats)
        
        if critical_count > 0 or error_count > total_components * 0.5:
            overall_status = 'critical'
        elif warning_count > total_components * 0.3:
            overall_status = 'warning'
        else:
            overall_status = 'healthy'
        
        return {
            'status': overall_status,
            'components_count': total_components,
            'healthy_count': healthy_count,
            'warning_count': warning_count,
            'critical_count': critical_count,
            'error_count': error_count,
            'last_update': datetime.now(timezone.utc).isoformat()
        }
    
    def get_component_status(self, name: str) -> Optional[Dict]:
        """Получить статус конкретного компонента"""
        return self.component_stats.get(name)
    
    def get_all_stats(self) -> Dict:
        """Получить все статистики"""
        return {
            'system_overview': self.get_system_overview(),
            'components': self.component_stats,
            'monitoring_active': self.is_running
        }


# Глобальный экземпляр системы мониторинга
_system_monitor: Optional[SystemMonitor] = None


def get_system_monitor() -> SystemMonitor:
    """Получить глобальный экземпляр системы мониторинга"""
    global _system_monitor
    
    if _system_monitor is None:
        _system_monitor = SystemMonitor()
    
    return _system_monitor


async def start_monitoring():
    """Запуск глобальной системы мониторинга"""
    monitor = get_system_monitor()
    await monitor.start()
    return monitor


async def stop_monitoring():
    """Остановка глобальной системы мониторинга"""
    global _system_monitor
    
    if _system_monitor:
        await _system_monitor.stop()
        _system_monitor = None
