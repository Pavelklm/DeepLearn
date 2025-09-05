import logging

def setup_logging(bot_name="Orchestrator"):
    """Настраивает единый формат логирования для всей системы."""
    # Формат будет включать имя процесса (бота)
    log_format = f"%(asctime)s - [{bot_name:<25}] - %(levelname)-8s - %(message)s"
    
    # Убираем все предыдущие настройки, чтобы избежать дублирования логов
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
        
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=[
            logging.FileHandler("trading_main.log", encoding='utf-8'), # Запись в общий файл
            logging.StreamHandler() # Вывод в консоль
        ]
    )