# Файл: orchestrator_service.py

import json
import multiprocessing
import time
import os
import logging
from bot_process import run_bot_process
from utils.logging_config import setup_logging

COMMANDS_DIR = "commands"

class Orchestrator:
    def __init__(self):
        self.running_bots = {} # Словарь: {'bot_name': process_object}
        if not os.path.exists(COMMANDS_DIR):
            os.makedirs(COMMANDS_DIR)
        
        setup_logging("Orchestrator")
        self.logger = logging.getLogger(__name__)

    def _check_for_commands(self):
        """Проверяет наличие новых команд в папке commands."""
        for command_file in sorted(os.listdir(COMMANDS_DIR)): # Сортируем для порядка выполнения
            if command_file.endswith(".json"):
                filepath = os.path.join(COMMANDS_DIR, command_file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        command_data = json.load(f)
                    
                    command_type = command_data.get("command")
                    
                    # ⭐ ИЗМЕНЕНИЕ: Обрабатываем разные типы команд
                    if command_type == "start":
                        self.start_new_bot(command_data)
                    elif command_type == "stop":
                        self.stop_bot(command_data.get("bot_name"))
                    elif command_type == "status":
                        self.show_status()
                    
                    os.remove(filepath)
                except Exception as e:
                    self.logger.error(f"Ошибка обработки команды {command_file}: {e}")
                    # В случае ошибки, перемещаем файл, чтобы не пытаться обработать его снова
                    os.rename(filepath, filepath + ".error")


    def start_new_bot(self, bot_config):
        """Запускает нового бота в отдельном процессе."""
        bot_name = bot_config.get('bot_name')
        if not bot_name:
            self.logger.warning("Попытка запустить бота без имени. Команда проигнорирована.")
            return
        if bot_name in self.running_bots and self.running_bots[bot_name].is_alive():
            self.logger.warning(f"Бот с именем '{bot_name}' уже запущен. Команда проигнорирована.")
            return
        
        process = multiprocessing.Process(target=run_bot_process, args=(bot_config,))
        self.running_bots[bot_name] = process
        process.start()
        self.logger.info(f"✅ Бот '{bot_name}' запущен в новом процессе (PID: {process.pid}).")

    # ⭐ НОВЫЙ МЕТОД
    def stop_bot(self, bot_name: str):
        """Останавливает бота по имени."""
        if not bot_name:
            self.logger.warning("Получена команда stop без имени бота.")
            return
            
        process = self.running_bots.get(bot_name)
        if process and process.is_alive():
            self.logger.info(f"Останавливаем бота '{bot_name}' (PID: {process.pid})...")
            process.terminate() # Отправляем сигнал на завершение
            process.join(timeout=10) # Ждем до 10 секунд
            if process.is_alive():
                self.logger.warning(f"Не удалось остановить бота '{bot_name}' gracefully. Убиваем процесс...")
                process.kill()
            self.logger.info(f"Бот '{bot_name}' остановлен.")
        else:
            self.logger.warning(f"Бот с именем '{bot_name}' не найден или уже не активен.")

    # ⭐ НОВЫЙ МЕТОД
    def show_status(self):
        """Выводит в лог информацию о работающих ботах."""
        self.logger.info("--- СТАТУС РАБОТАЮЩИХ БОТОВ ---")
        if not self.running_bots:
            self.logger.info("Нет активных ботов.")
        else:
            for bot_name, process in self.running_bots.items():
                status = "Активен" if process.is_alive() else "Завершен"
                self.logger.info(f"  - Бот: {bot_name:<30} | PID: {process.pid:<10} | Статус: {status}")
        self.logger.info("---------------------------------")


    def monitor_bots(self):
        """Проверяет состояние запущенных ботов и удаляет завершенные."""
        for bot_name, process in list(self.running_bots.items()):
            if not process.is_alive():
                self.logger.info(f"ℹ️ Бот '{bot_name}' (PID: {process.pid}) завершил свою работу (Код выхода: {process.exitcode}).")
                del self.running_bots[bot_name]

    def run_forever(self):
        """Главный цикл сервиса."""
        self.logger.info("✅ Оркестратор запущен и слушает команды...")
        try:
            while True:
                self._check_for_commands()
                self.monitor_bots()
                time.sleep(5)
        except KeyboardInterrupt:
            self.logger.info("Получен сигнал KeyboardInterrupt. Завершение работы Оркестратора...")
            # Корректно останавливаем все дочерние процессы
            for bot_name in list(self.running_bots.keys()):
                self.stop_bot(bot_name)
            print("Оркестратор остановлен.")

if __name__ == "__main__":
    orchestrator = Orchestrator()
    orchestrator.run_forever()