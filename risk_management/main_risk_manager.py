"""RiskManager с улучшенным выводом для бэктеста и конфигурацией"""
import logging
import json
import os
import time
from typing import Dict, Any, List, TypedDict, Optional
from datetime import datetime

from .config_manager import ConfigManager, Config
from .binance_client import BinanceClient
from .risk_calculator import RiskCalculator
from .performance_tracker import PerformanceTracker
from .telegram_notifier import TelegramNotifier


logger = logging.getLogger(__name__)


# ... (классы LimitViolation и RiskCheckResult без изменений) ...
class LimitViolation(TypedDict):
    type: str
    current: float
    limit: float


class RiskCheckResult(TypedDict):
    trade_allowed: bool
    balance: float
    violated_limits: List[LimitViolation]
    reasons: List[str]


# ---------------------- RiskManager ----------------------
class RiskManager:
    """Класс-оркестратор системы риск-менеджмента с режимами live, paper и backtest"""

    # ⭐ ИЗМЕНЕНИЕ: Упрощаем конструктор
    def __init__(self, config: Config, performance_tracker: PerformanceTracker, mode: str = "live"):
        self.mode = mode
        self.config = config
        self.performance_tracker = performance_tracker # Принимаем готовый объект
        self.silent_mode = mode == "backtest"
        self.balance: float = self.config.trading.initial_balance

        self.binance_client: BinanceClient | None = None
        if self.mode == "live":
            self.binance_client = BinanceClient(
                self.config.binance_api_key, self.config.binance_api_secret
            )

        self.risk_calculator = RiskCalculator(self.config)
        self.telegram_notifier = TelegramNotifier(self.config)

        self.active_trades: Dict[str, Any] = {}
        # Логика state_file остается для режимов paper/live для хранения АКТИВНЫХ сделок
        self.state_file = "" # Будет устанавливаться извне

        if self.mode in ("paper", "backtest"):
            # Загружаем только активные сделки, баланс управляется извне
            state = self._load_state()
            self.active_trades = state.get("active_trades", {})
            self.balance = state.get("balance", self.config.trading.initial_balance)
        
        if not self.silent_mode:
            logger.info(f"RiskManager инициализирован в режиме {self.mode}")
            self.telegram_notifier.notify_system_status(
                "started", f"Система риск-менеджмента запущена в режиме {self.mode}"
            )

    # ... (методы _print_backtest_header и _print_backtest_summary удалены, т.к. это задача отчетности)
    
    # ... (остальные методы остаются, но с небольшими изменениями)

    def _get_initial_state(self) -> Dict[str, Any]:
        """Возвращает начальное состояние на основе конфига."""
        return {
            "balance": self.config.trading.initial_balance,
            "active_trades": {}
        }

    def _init_state_file(self):
        if self.state_file and not os.path.exists(self.state_file):
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self._get_initial_state(), f, indent=2)

    def _load_state(self) -> Dict[str, Any]:
        if self.state_file and os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Ошибка загрузки state файла {self.state_file}: {e}")
        return self._get_initial_state()

    def _save_state(self, state: Dict[str, Any]):
        if self.state_file:
            try:
                with open(self.state_file, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2)
            except IOError as e:
                logger.error(f"Ошибка сохранения state файла {self.state_file}: {e}")

    def get_balance(self) -> float:
        if self.mode == "live" and self.binance_client is not None:
            return self.binance_client.get_account_balance("USDT") or 0.0
        return self.balance

    def check_trading_allowed(self) -> RiskCheckResult:
        risk_check = self.performance_tracker.check_risk_limits()
        balance = self.get_balance()
        allowed = bool(risk_check.get("trade_allowed", False)) and balance > 0
        violated_limits = risk_check.get("violated_limits", [])
        reasons = risk_check.get("reasons", [])

        if balance <= 0:
            allowed = False
            reasons.append("Недостаточный баланс")

        if not self.silent_mode:
            logger.info(f"Trade allowed: {allowed}, Balance: {balance}")
        
        return {
            "trade_allowed": allowed,
            "balance": balance,
            "violated_limits": violated_limits,
            "reasons": reasons,
        }

    def calculate_trade_parameters(
        self, entry_price: float, target_tp_price: Optional[float], suggested_sl_price: Optional[float], side: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Вызывает RiskCalculator с полным набором параметров для получения деталей сделки.
        """
        balance = self.get_balance()
        trade_history = [
            {"success": t.success, "profit": t.profit, "timestamp": t.timestamp}
            for t in self.performance_tracker.trade_history
        ]
        
        # ИСПРАВЛЕНО: Определяем направление сделки правильно
        if side is None:
            # Используем конфигурируемый дефолтный процент прибыли для лонга
            default_tp_multiplier = 1 + self.config.trading.default_tp_percent_for_long
            final_tp_for_side_check = target_tp_price or entry_price * default_tp_multiplier
            side = "BUY" if final_tp_for_side_check > entry_price else "SELL"
        
        # ДОПОЛНИТЕЛЬНАЯ ПРОВЕРКА: убедимся что все параметры логически согласованы с определенным направлением
        if suggested_sl_price is not None:
            if side == "BUY" and suggested_sl_price >= entry_price:
                raise ValueError(
                    f"Invalid SL for {side} trade: SL price ({suggested_sl_price}) must be below entry price ({entry_price}). "
                    f"For BUY trades, stop-loss should protect against downward price movement."
                )
            elif side == "SELL" and suggested_sl_price <= entry_price:
                raise ValueError(
                    f"Invalid SL for {side} trade: SL price ({suggested_sl_price}) must be above entry price ({entry_price}). "
                    f"For SELL trades, stop-loss should protect against upward price movement."
                )
        
        position = self.risk_calculator.calculate_position(
            entry_price=entry_price,
            target_tp_price=target_tp_price,
            current_balance=balance,
            trade_history=trade_history,
            suggested_sl_price=suggested_sl_price,
            side=side
        )
        
        final_tp_for_side_check = target_tp_price or position.final_tp_price
        quantity = position.position_size_usd / entry_price if entry_price else 0.0
        
        return {
            "side": side,
            "quantity": quantity,
            "tp_price": position.final_tp_price,
            "sl_price": position.sl_price,
            "position_size_usd": position.position_size_usd,
            "expected_profit": position.tp_net_profit,
            "expected_loss": position.sl_net_loss,
            "risk_reward_ratio": (
                position.tp_net_profit / abs(position.sl_net_loss)
                if position.sl_net_loss and position.sl_net_loss != 0
                else 0.0
            ),
        }

    def execute_trade(
        self, 
        entry_price: float, 
        target_tp_price: Optional[float], 
        symbol: str = "BTCUSDT",
        suggested_sl_price: Optional[float] = None,
        side: Optional[str] = None,
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Основной метод для выполнения сделки.
        """
        try:
            self._validate_trade_params(entry_price, target_tp_price, symbol, suggested_sl_price)
        except ValueError as e:
            logger.error(f"Ошибка валидации: {e}")
            return {"trade_allowed": False, "order_placed": False, "reason": f"Ошибка валидации: {e}"}
        
        allowed_info = self.check_trading_allowed()
        if not allowed_info["trade_allowed"]:
            return {"trade_allowed": False, "order_placed": False, "reason": "; ".join(allowed_info["reasons"])}
        
        # КРИТИЧЕСКАЯ ПРОВЕРКА: лимит одновременных позиций
        active_trades_count = len(self.active_trades)
        max_concurrent = self.config.trading.max_concurrent_trades
        if active_trades_count >= max_concurrent:
            error_msg = (
                f"Превышен лимит одновременных позиций: "
                f"{active_trades_count}/{max_concurrent}. Закройте существующие позиции перед открытием новых."
            )
            if not self.silent_mode:
                logger.warning(error_msg)
            return {"trade_allowed": False, "order_placed": False, "reason": error_msg}

        trade_params = self.calculate_trade_parameters(entry_price, target_tp_price, suggested_sl_price, side)
        
        order_id = f"{self.mode}_{int(time.time() * 1000)}"
        trade_result = {
            "trade_allowed": True, "order_placed": True, "order_id": order_id,
            "symbol": symbol, "entry_price": entry_price, **trade_params,
        }

        self.active_trades[order_id] = {
            "symbol": symbol,
            "entry_price": entry_price,
            "quantity": trade_result["quantity"],
            "side": trade_params["side"], 
            "timestamp": timestamp or datetime.now().isoformat(),
            "target_tp_price": target_tp_price,
            "suggested_sl_price": suggested_sl_price,
            "tp_price": trade_params.get("tp_price"),
            "sl_price": trade_params.get("sl_price"),
        }

        if self.mode in ("paper", "backtest"):
            state = self._load_state()
            state["active_trades"][order_id] = self.active_trades[order_id]
            self._save_state(state)

        if not self.silent_mode:
            self.telegram_notifier.notify_trade_executed(trade_result)
            logger.info(f"Параметры сделки рассчитаны: {trade_result}")

        return trade_result

    def update_trade_result(
        self, order_id: str, exit_price: float, trade_type: str = "TP",
        timestamp: Optional[str] = None
    ) -> Dict[str, Any]:
        # КРИТИЧЕСКАЯ ВАЛИДАЦИЯ: проверка exit_price
        if not isinstance(exit_price, (int, float)) or exit_price <= 0:
            error_msg = f"Invalid exit_price: {exit_price}. Must be a positive number."
            if not self.silent_mode:
                logger.error(error_msg)
            return {"success": False, "reason": error_msg}
        
        # ВАЛИДАЦИЯ: проверка trade_type
        valid_trade_types = {"TP", "SL", "MANUAL"}
        if trade_type not in valid_trade_types:
            error_msg = f"Invalid trade_type: {trade_type}. Must be one of {valid_trade_types}"
            if not self.silent_mode:
                logger.error(error_msg)
            return {"success": False, "reason": error_msg}
        
        # ВАЛИДАЦИЯ: проверка timestamp если передан
        if timestamp is not None:
            try:
                datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
            except (ValueError, TypeError):
                error_msg = f"Invalid timestamp format: {timestamp}. Must be ISO format."
                if not self.silent_mode:
                    logger.error(error_msg)
                return {"success": False, "reason": error_msg}
        
        trade_info = self.active_trades.get(order_id)
        if not trade_info:
            if not self.silent_mode:
                logger.warning(f"Сделка {order_id} не найдена среди активных")
            return {"success": False, "reason": "Trade not found"}

        entry_price = trade_info["entry_price"]
        executed_qty = trade_info["quantity"]
        side = trade_info.get("side", "BUY")
        position_size_usd = executed_qty * entry_price

        if side == "BUY":
            gross_pnl = executed_qty * (exit_price - entry_price)
        else: # SELL
            gross_pnl = executed_qty * (entry_price - exit_price)

        entry_fee_cost = position_size_usd * self.config.fees.entry_fee
        exit_fee_rate = self.config.fees.sl_fee if trade_type == "SL" else self.config.fees.tp_fee
        exit_value_usd = executed_qty * exit_price
        exit_fee_cost = exit_value_usd * exit_fee_rate
        
        profit = gross_pnl - entry_fee_cost - exit_fee_cost
        success = profit > 0
        
        trade_result = {
            "entry_timestamp": trade_info["timestamp"],
            "timestamp": timestamp or datetime.now().isoformat(), 
            "entry_price": entry_price,
            "exit_price": exit_price, "profit": profit, "success": success,
            "position_size_usd": position_size_usd, "trade_type": trade_type,
        }

        self.performance_tracker.update_trade_statistics(trade_result)
        
        if self.mode in ("paper", "backtest"):
            # КРИТИЧЕСКАЯ ПРОВЕРКА: защита от отрицательного баланса
            new_balance = self.balance + profit
            if new_balance < 0:
                warning_msg = (
                    f"КРИТИЧЕСКО: Отрицательный баланс! "
                    f"Текущий: {self.balance:.2f}, Прибыль: {profit:.2f}, "
                    f"Новый баланс: {new_balance:.2f}. Устанавливаем баланс = 0"
                )
                if not self.silent_mode:
                    logger.error(warning_msg)
                self.balance = 0.0  # Минимальный возможный баланс
            else:
                self.balance = new_balance
            
            self.active_trades.pop(order_id, None)
            state = {"balance": self.balance, "active_trades": self.active_trades}
            self._save_state(state)
        else:
             self.active_trades.pop(order_id, None)

        if not self.silent_mode:
            self.telegram_notifier.notify_trade_closed(trade_result)
            logger.info(f"Сделка {order_id} обновлена: {trade_result}")
        
        return trade_result

    def get_current_status(self) -> Dict[str, Any]:
        """Возвращает только оперативные данные, без генерации отчетов."""
        balance = self.get_balance()
        stats = self.performance_tracker.get_statistics_summary()
        risk_limits = self.performance_tracker.check_risk_limits()
        
        status = {
            "balance": balance, "statistics": stats, "risk_limits": risk_limits,
            "system_healthy": risk_limits.get("trade_allowed", False) and balance > 0,
            "timestamp": datetime.now().isoformat(),
        }
        return status

    def _validate_trade_params(self, entry_price: float, target_tp_price: Optional[float], symbol: str, suggested_sl_price: Optional[float]) -> None:
        """Валидация параметров сделки."""
        if not isinstance(entry_price, (int, float)) or entry_price <= 0:
            raise ValueError(f"Entry price must be a positive number, got: {entry_price}")
        
        if target_tp_price is not None:
            if not isinstance(target_tp_price, (int, float)) or target_tp_price <= 0:
                 raise ValueError(f"TP price must be a positive number, got: {target_tp_price}")

            price_diff_pct = abs(target_tp_price - entry_price) / entry_price
            min_profit_target = self.config.validation.min_profit_target_pct
            max_profit_target = self.config.validation.max_profit_target_pct
            
            if price_diff_pct < min_profit_target:
                raise ValueError(f"TP too close to entry price. Diff: {price_diff_pct:.4f}, min: {min_profit_target}")
            
            if price_diff_pct > max_profit_target:
                raise ValueError(f"TP too far from entry price. Diff: {price_diff_pct:.4f}, max: {max_profit_target}")
        
        if suggested_sl_price is not None:
            if not isinstance(suggested_sl_price, (int, float)) or suggested_sl_price <= 0:
                raise ValueError(f"Suggested SL price must be a positive number, got: {suggested_sl_price}")
        
        # НОВАЯ ВАЛИДАЦИЯ: проверка логической согласованности направления сделки
        if target_tp_price is not None and suggested_sl_price is not None:
            # Определяем направление по TP
            inferred_side = "BUY" if target_tp_price > entry_price else "SELL"
            
            if inferred_side == "BUY":
                if suggested_sl_price >= entry_price:
                    raise ValueError(
                        f"Invalid trade parameters for BUY direction: "
                        f"SL price ({suggested_sl_price}) must be below entry price ({entry_price}). "
                        f"Current setup would result in guaranteed loss on stop-loss execution."
                    )
            else:  # SELL
                if suggested_sl_price <= entry_price:
                    raise ValueError(
                        f"Invalid trade parameters for SELL direction: "
                        f"SL price ({suggested_sl_price}) must be above entry price ({entry_price}). "
                        f"Current setup would result in guaranteed loss on stop-loss execution."
                    )

        if not isinstance(symbol, str) or not symbol.strip():
            raise ValueError(f"Symbol must be a non-empty string, got: {symbol}")
        
        if not self.silent_mode:
            logger.info(f"✅ Validation passed: entry={entry_price}, tp={target_tp_price}, sl={suggested_sl_price}")

    def shutdown(self) -> None:
        if not self.silent_mode:
            logger.info("Завершение работы RiskManager")
            self.telegram_notifier.notify_system_status(
                "stopped", f"Система риск-менеджмента остановлена ({self.mode})"
            )