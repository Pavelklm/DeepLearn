#!/usr/bin/env python3
"""
Полная проверка здоровья системы сканера больших ордеров
Согласно спецификации
"""

import asyncio
import aiofiles
import psutil
import json
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, List

# Добавляем корневую директорию в путь
import sys
sys.path.append(str(Path(__file__).parent.parent))

from config.main_config import *

class HealthChecker:
    """Проверка здоровья системы согласно спецификации"""
    
    def __init__(self):
        self.results = {}
        
    async def health_check(self) -> Dict:
        """Полная проверка здоровья системы"""
        
        checks = {
            "api_connectivity": await self.check_api_connections(),
            "hot_pool_activity": await self.check_hot_pool(),
            "websocket_server": await self.check_websocket(),
            "file_updates": await self.check_file_freshness(),
            "memory_usage": self.check_system_resources(),
            "disk_space": self.check_disk_space()
        }
        
        # Отправка результатов в мониторинг
        await self.send_health_report(checks)
        
        return checks
    
    async def check_api_connections(self) -> bool:
        """Проверка подключений к API бирж"""
        try:
            from src.exchanges.exchange_factory import get_exchange
            
            # Проверяем основную биржу
            exchange = await get_exchange("binance")
            if not exchange:
                return False
                
            # Тестовый запрос
            pairs = await exchange.get_futures_pairs()
            return len(pairs) > 0
            
        except Exception as e:
            print(f"Ошибка проверки API: {e}")
            return False
    
    async def check_hot_pool(self) -> bool:
        """Проверка активности горячего пула"""
        try:
            hot_orders_file = Path(FILE_CONFIG["hot_orders_file"])
            
            if not hot_orders_file.exists():
                return False
            
            # Проверяем свежесть файла (не старше 2 минут)
            file_age = datetime.now().timestamp() - hot_orders_file.stat().st_mtime
            return file_age < 120  # 2 минуты
            
        except Exception as e:
            print(f"Ошибка проверки горячего пула: {e}")
            return False
    
    async def check_websocket(self) -> bool:
        """Проверка WebSocket сервера"""
        try:
            import websockets
            from config.websocket_config import WEBSOCKET_CONFIG
            
            uri = f"ws://localhost:{WEBSOCKET_CONFIG['port']}/public"
            
            # Попытка подключения с таймаутом
            async with asyncio.timeout(5):
                async with websockets.connect(uri) as websocket:
                    # Отправляем пинг
                    await websocket.send('{"type": "ping"}')
                    response = await websocket.recv()
                    return "pong" in response.lower()
                    
        except Exception as e:
            print(f"Ошибка проверки WebSocket: {e}")
            return False
    
    async def check_file_freshness(self) -> bool:
        """Проверка свежести обновлений файлов"""
        try:
            files_to_check = [
                FILE_CONFIG["hot_orders_file"],
                "logs/scanner.log"
            ]
            
            for file_path in files_to_check:
                path = Path(file_path)
                if path.exists():
                    # Файл не должен быть старше 5 минут
                    file_age = datetime.now().timestamp() - path.stat().st_mtime
                    if file_age > 300:  # 5 минут
                        return False
            
            return True
            
        except Exception as e:
            print(f"Ошибка проверки файлов: {e}")
            return False
    
    def check_system_resources(self) -> bool:
        """Проверка системных ресурсов"""
        try:
            # Проверяем память
            memory = psutil.virtual_memory()
            if memory.percent > MONITORING_CONFIG["alert_thresholds"]["memory_usage"]:
                return False
            
            # Проверяем CPU
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > MONITORING_CONFIG["alert_thresholds"]["cpu_usage"]:
                return False
            
            return True
            
        except Exception as e:
            print(f"Ошибка проверки ресурсов: {e}")
            return False
    
    def check_disk_space(self) -> bool:
        """Проверка дискового пространства"""
        try:
            disk_usage = psutil.disk_usage('.')
            # Проверяем, что свободно больше 1GB
            free_gb = disk_usage.free / (1024**3)
            return free_gb > 1.0
            
        except Exception as e:
            print(f"Ошибка проверки диска: {e}")
            return False
    
    async def send_health_report(self, checks: Dict):
        """Отправка отчета о здоровье системы"""
        try:
            report = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "checks": checks,
                "overall_health": all(checks.values()),
                "failed_checks": [name for name, result in checks.items() if not result]
            }
            
            # Сохраняем отчет в файл
            report_file = Path("data/health_report.json")
            async with aiofiles.open(report_file, 'w') as f:
                await f.write(json.dumps(report, indent=2))
            
            # Выводим результат
            print(f"Health Check: {'✅ PASSED' if report['overall_health'] else '❌ FAILED'}")
            if report['failed_checks']:
                print(f"Проваленные проверки: {', '.join(report['failed_checks'])}")
                
        except Exception as e:
            print(f"Ошибка отправки отчета: {e}")


async def main():
    """Главная функция проверки здоровья"""
    checker = HealthChecker()
    result = await checker.health_check()
    
    # Возвращаем код выхода
    return all(result.values())


if __name__ == "__main__":
    result = asyncio.run(main())
    exit(0 if result else 1)
