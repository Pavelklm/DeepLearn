#!/usr/bin/env python3
"""
Криптовалютный сканнер больших ордеров
Главный файл запуска системы
"""

import asyncio
import argparse
import signal
import sys
from pathlib import Path

# Добавляем корневую директорию в путь
sys.path.append(str(Path(__file__).parent))

from src.scanner_orchestrator import ScannerOrchestrator
from config.main_config import *
from src.utils.logger import setup_logger

logger = setup_logger(__name__)

class CryptoScannerApp:
    """Главный класс приложения"""
    
    def __init__(self, args):
        self.args = args
        self.orchestrator = None
        self.websocket_server = None
        self.running = False
        self.logger = logger
    
    async def start(self):
        """Запуск всей системы"""
        self.logger.info("🚀 Запуск криптовалютного сканнера больших ордеров")
        
        try:
            # 1. Инициализация оркестратора (управление пулами)
            self.orchestrator = ScannerOrchestrator(
                exchanges=self.args.exchanges,
                testnet=self.args.dev
            )
            
            # 2. Запуск сканирования (WebSocket управляется внутри оркестратора)
            await self.orchestrator.start()
            
            self.running = True
            self.logger.info("✅ Система успешно запущена")
            
            # 3. Основной цикл работы
            if self.args.primary_scan_only:
                await self.orchestrator.run_test_mode()
            else:
                await self.orchestrator.run_continuous_mode()
                
        except Exception as e:
            self.logger.error(f"❌ Критическая ошибка при запуске: {e}")
            await self.stop()
            raise
    
    async def _main_loop(self):
        """Основной цикл работы системы (не используется - заменен на orchestrator.run_continuous_mode())"""
        # Этот метод больше не нужен - логика перенесена в ScannerOrchestrator.run_continuous_mode()
        pass
    
    async def stop(self):
        """Graceful shutdown"""
        self.logger.info("🛑 Остановка системы...")
        self.running = False
        
        if self.orchestrator:
            await self.orchestrator.stop()
            
        self.logger.info("✅ Система остановлена")

def setup_signal_handlers(app):
    """Настройка обработчиков сигналов для graceful shutdown"""
    def signal_handler(signum, frame):
        logger.info(f"🔔 Получен сигнал {signum}")
        asyncio.create_task(app.stop())
    
    signal.signal(signal.SIGINT, signal_handler)   # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler)  # kill

def parse_arguments():
    """Парсинг аргументов командной строки"""
    parser = argparse.ArgumentParser(
        description="Криптовалютный сканнер больших ордеров"
    )
    
    parser.add_argument(
        "--dev", 
        action="store_true",
        help="Режим разработки (больше логов, тестовые данные)"
    )
    
    parser.add_argument(
        "--primary-scan-only",
        action="store_true", 
        help="Выполнить только первичное сканирование и остановиться"
    )
    
    parser.add_argument(
        "--exchanges",
        nargs="+",
        default=["binance"],
        help="Список бирж для сканирования (по умолчанию: binance)"
    )
    
    parser.add_argument(
        "--config",
        help="Путь к альтернативному файлу конфигурации"
    )
    
    parser.add_argument(
        "--status",
        action="store_true",
        help="Показать статус работающей системы и выйти"
    )
    
    return parser.parse_args()

async def main():
    """Точка входа в приложение"""
    args = parse_arguments()
    
    # Проверка статуса
    if args.status:
        # TODO: Реализовать проверку статуса через IPC/файл
        print("📊 Проверка статуса системы...")
        return
    
    # Создание и запуск приложения
    app = CryptoScannerApp(args)
    setup_signal_handlers(app)
    
    try:
        await app.start()
    except KeyboardInterrupt:
        logger.info("👋 Получен сигнал прерывания")
    except Exception as e:
        logger.error(f"💥 Фатальная ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    # Настройка event loop политик для оптимальной производительности
    if sys.platform == "linux":
        asyncio.set_event_loop_policy(asyncio.UnixEventLoopPolicy())
    
    # Запуск приложения
    asyncio.run(main())
