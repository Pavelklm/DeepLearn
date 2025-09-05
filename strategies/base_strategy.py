# Файл: trading/strategies/base_strategy.py

from abc import ABC, abstractmethod
import pandas as pd
from typing import Any, Dict

class BaseStrategy(ABC):
    """
    Абстрактный базовый класс для всех торговых стратегий.
    """
    @property
    @abstractmethod
    def name(self) -> str:
        """Имя стратегии для отображения в логах и отчетах."""
        pass

    @abstractmethod
    def analyze(self, historical_data: pd.DataFrame) -> dict:
        """
        Основной метод анализа. Принимает DataFrame с историческими данными.
        """
        pass

    # НОВЫЕ МЕТОДЫ
    def update(self, candle: Any):
        """
        Метод для обновления состояния стратегии на каждой новой свече.
        По умолчанию ничего не делает, но может быть переопределен.
        """
        pass

    def check_entry_signal(self) -> Dict[str, Any] | None:
        """
        Проверяет наличие сигнала на вход.
        Возвращает словарь с параметрами, если сигнал есть, иначе None.
        """
        return None

    def check_exit_signal(self, trade: Dict[str, Any]) -> bool:
        """
        Проверяет наличие сигнала на выход для активной сделки.
        Возвращает True, если нужно выйти.
        """
        return False