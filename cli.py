# Файл: cli.py

import json
import os
import time
import argparse

from bot_process import Playground

COMMANDS_DIR = "commands"

def create_command_file(command_data: dict):
    """Универсальная функция для создания файлов-команд."""
    command_type = command_data.get("command")
    bot_name = command_data.get("bot_name", "")
    
    # Имя файла-команды должно быть уникальным
    # Для команды stop оно будет включать имя бота
    if command_type == 'stop' and bot_name:
        command_filename = f"{int(time.time())}_{command_type}_{bot_name}.json"
    else:
        command_filename = f"{int(time.time())}_{command_type}.json"
        
    command_filepath = os.path.join(COMMANDS_DIR, command_filename)

    with open(command_filepath, 'w', encoding='utf-8') as f:
        json.dump(command_data, f)
    
    print(f"✅ Команда '{command_type}' отправлена Оркестратору.")


def start_bot(config_file: str):
    """Создает файл-команду для запуска нового бота."""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            config = json.load(f)
    except FileNotFoundError:
        print(f"❌ Ошибка: файл конфигурации '{config_file}' не найден.")
        return
    except json.JSONDecodeError:
        print(f"❌ Ошибка: файл '{config_file}' содержит невалидный JSON.")
        return

    if not config.get("bot_name"):
        print("❌ Ошибка: в файле конфигурации отсутствует обязательное поле 'bot_name'.")
        return

    config["command"] = "start"
    create_command_file(config)


def stop_bot(bot_name: str):
    """Создает файл-команду для остановки бота."""
    command_data = {"command": "stop", "bot_name": bot_name}
    create_command_file(command_data)


def get_status():
    """Создает файл-команду для получения статуса."""
    command_data = {"command": "status"}
    create_command_file(command_data)


if __name__ == "__main__":
    if not os.path.exists(COMMANDS_DIR):
        os.makedirs(COMMANDS_DIR)

    parser = argparse.ArgumentParser(description="Интерфейс управления для торгового оркестратора.")
    subparsers = parser.add_subparsers(dest="command_name", help="Доступные команды", required=True)

    # Команда 'start'
    start_parser = subparsers.add_parser("start", help="Запустить нового бота по файлу конфигурации.")
    start_parser.add_argument("config", help="Путь к JSON файлу с конфигурацией бота (например, bots.json).")

    # ⭐ НОВАЯ КОМАНДА 'stop'
    stop_parser = subparsers.add_parser("stop", help="Остановить работающего бота по имени.")
    stop_parser.add_argument("bot_name", help="Имя бота, которого нужно остановить.")

    # ⭐ НОВАЯ КОМАНДА 'status'
    status_parser = subparsers.add_parser("status", help="Показать список всех работающих ботов.")

    args = parser.parse_args()

    if args.command_name == "start":
        start_bot(args.config)
    elif args.command_name == "stop":
        stop_bot(args.bot_name)
    elif args.command_name == "status":
        get_status()
    else:
        parser.print_help()