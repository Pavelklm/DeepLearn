"""Модуль отслеживания производительности и статистики с поддержкой режимов"""

import logging
from datetime import datetime, date
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

from .config_manager import Config

logger = logging.getLogger(__name__)


@dataclass
class TradeResult:
    """Результат торговой сделки"""
    entry_timestamp: str
    timestamp: str
    entry_price: float
    exit_price: float
    profit: float
    success: bool
    position_size: float
    trade_type: str


@dataclass
class DailyStats:
    """Дневная статистика"""
    date: str
    total_profit: float = 0.0
    trades_count: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    # Счетчик убыточных сделок подряд ИМЕННО ЗА ЭТОТ ДЕНЬ
    consecutive_losses: int = 0


class PerformanceTracker:
    def __init__(self, config: Config):
        """
        Инициализирует трекер. Работает только в оперативной памяти.
        """
        self.config = config
        self.trade_history: List[TradeResult] = []
        self.daily_stats: Dict[str, DailyStats] = {}
        logger.info("PerformanceTracker (in-memory) инициализирован.")

    def update_trade_statistics(self, trade_result: Dict[str, Any]) -> None:
        """Обновление статистики после каждой сделки."""
        trade = TradeResult(
            entry_timestamp=trade_result.get('entry_timestamp', datetime.now().isoformat()),
            timestamp=trade_result.get('timestamp', datetime.now().isoformat()),
            entry_price=trade_result.get('entry_price', 0.0),
            exit_price=trade_result.get('exit_price', 0.0),
            profit=trade_result.get('profit', 0.0),
            success=trade_result.get('success', False),
            position_size=trade_result.get('position_size_usd', 0.0),
            trade_type=trade_result.get('trade_type', 'UNKNOWN')
        )
        self.trade_history.append(trade)

        trade_date = datetime.fromisoformat(trade.timestamp).date().isoformat()
        # Если для этой даты еще нет статистики, создаем ее
        if trade_date not in self.daily_stats:
            self.daily_stats[trade_date] = DailyStats(date=trade_date)

        daily_stat = self.daily_stats[trade_date]
        daily_stat.total_profit += trade.profit
        daily_stat.trades_count += 1
        
        if trade.success:
            daily_stat.winning_trades += 1
            # Прибыльная сделка сбрасывает счетчик убытков за день
            daily_stat.consecutive_losses = 0
        else:
            daily_stat.losing_trades += 1
            # Убыточная сделка увеличивает счетчик за день
            daily_stat.consecutive_losses += 1

        logger.info(
            f"Статистика за {trade_date} обновлена: "
            f"Прибыль={daily_stat.total_profit:.2f}, "
            f"Сделок={daily_stat.trades_count}, "
            f"Убытков подряд за день={daily_stat.consecutive_losses}"
        )

    def get_daily_drawdown(self, target_date: Optional[str] = None) -> float:
        """
        [ИСПРАВЛЕНО] Рассчитывает дневную просадку как процент от НАЧАЛЬНОГО БАЛАНСА.
        """
        if target_date is None:
            target_date = date.today().isoformat()
        
        daily_stat = self.daily_stats.get(target_date)
        # Если нет статистики или день в плюсе, просадки нет
        if not daily_stat or daily_stat.total_profit >= 0:
            return 0.0
        
        initial_balance = self.config.trading.initial_balance
        if initial_balance > 0:
            # Возвращаем просадку как положительное число (например, 0.05 для 5%)
            return abs(daily_stat.total_profit) / initial_balance
        
        return 0.0

    def get_daily_consecutive_losses(self, target_date: Optional[str] = None) -> int:
        """
        [НОВАЯ ФУНКЦИЯ] Возвращает количество убыточных сделок подряд за указанный день.
        """
        if target_date is None:
            target_date = date.today().isoformat()
        
        daily_stat = self.daily_stats.get(target_date)
        return daily_stat.consecutive_losses if daily_stat else 0

    def _count_consecutive_serious_problem_days(self) -> int:
        """
        ИСПРАВЛЕНО: Считает количество ПОСЛЕДНИХ дней подряд с серьезными проблемами.
        
        День считается "проблемным" если:
        1. Было ≥max_consecutive_losses_per_day убыточных сделок подряд ЗА ЭТОТ ДЕНЬ
        2. ИЛИ дневная просадка ≥max_daily_drawdown от капитала
        """
        sorted_dates = sorted(self.daily_stats.keys(), reverse=True)
        serious_problem_days_count = 0
        
        for date_str in sorted_dates:
            daily_stat = self.daily_stats[date_str]
            
            # Пропускаем дни без сделок
            if daily_stat.trades_count == 0:
                continue
                
            # Проверяем критерии "серьезной проблемы"
            has_consecutive_losses_problem = daily_stat.consecutive_losses >= self.config.trading.max_consecutive_losses_per_day
            
            # Рассчитываем дневную просадку
            daily_drawdown = self.get_daily_drawdown(date_str)
            has_drawdown_problem = daily_drawdown >= self.config.trading.max_daily_drawdown
            
            # Если есть хотя бы одна серьезная проблема - день считается проблемным
            if has_consecutive_losses_problem or has_drawdown_problem:
                serious_problem_days_count += 1
            else:
                # Прерываем счет, как только находим "нормальный" день
                break
                
        return serious_problem_days_count

    def check_risk_limits(self) -> Dict[str, Any]:
        """
        [ИСПРАВЛЕНО] Проверяет все три уровня защиты.
        """
        result = {'trade_allowed': True, 'violated_limits': [], 'reasons': []}
        today_str = date.today().isoformat()

        # УРОВЕНЬ 1: Проверка на максимальную дневную просадку (например, 5%)
        drawdown = self.get_daily_drawdown(today_str)
        if drawdown >= self.config.trading.max_daily_drawdown:
            result['trade_allowed'] = False
            result['violated_limits'].append('daily_drawdown')
            result['reasons'].append(f"Дневная просадка {drawdown:.2%} превысила лимит {self.config.trading.max_daily_drawdown:.2%}")
            
        # УРОВЕНЬ 2: Проверка на убыточные сделки подряд за день (например, 3)
        consecutive_losses = self.get_daily_consecutive_losses(today_str)
        limit_consecutive = self.config.trading.max_consecutive_losses_per_day
        if consecutive_losses >= limit_consecutive:
            result['trade_allowed'] = False
            result['violated_limits'].append('consecutive_losses_per_day')
            result['reasons'].append(f"Достигнут лимит убыточных сделок подряд за день: {consecutive_losses}/{limit_consecutive}")

        # УРОВЕНЬ 3: ИСПРАВЛЕНО - Проверка на серьезные проблемы несколько дней подряд
        serious_problem_days = self._count_consecutive_serious_problem_days()
        if serious_problem_days >= self.config.trading.max_losing_days:
            result['trade_allowed'] = False
            result['violated_limits'].append('max_serious_problem_days')
            result['reasons'].append(
                f"КРИТИЧЕСКАЯ СИТУАЦИЯ: Бот остановлен! "
                f"{serious_problem_days} дней подряд с серьезными проблемами "
                f"(≥{self.config.trading.max_consecutive_losses_per_day} убыточных сделок подряд "
                f"или ≥{self.config.trading.max_daily_drawdown:.1%} просадка за день)"
            )
        
        return result

    def get_statistics_summary(self) -> Dict[str, Any]:
        """Возвращает общую статистику по всем сделкам."""
        if not self.trade_history:
            return {}
        
        total_trades = len(self.trade_history)
        total_profit = sum(trade.profit for trade in self.trade_history)
        winning_trades = sum(1 for t in self.trade_history if t.success)
        
        return {
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': total_trades - winning_trades,
            'winrate': (winning_trades / total_trades) if total_trades > 0 else 0.0,
            'total_profit': total_profit,
        }