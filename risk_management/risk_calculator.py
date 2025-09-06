"""
Модуль расчета риска и позиций.
Содержит логику расчета размера позиции, стоп-лоссов, тейк-профитов и потенциального PnL.
Использует конфигурацию для трейдинга и адаптивной стратегии.
"""

from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
from decimal import Decimal, getcontext, ROUND_HALF_UP
from .config_manager import Config  # относительный импорт Config из текущего пакета

# Устанавливаем точность Decimal и метод округления для финансовых расчетов
getcontext().prec = 18
getcontext().rounding = ROUND_HALF_UP


@dataclass
class PositionCalculationResult:
    """
    Структура для возврата результатов расчета позиции.
    Содержит финальные цены TP и SL, размер позиции и ожидаемую прибыль/убыток.
    """
    final_tp_price: float
    sl_price: float
    position_size_usd: float
    tp_net_profit: float
    sl_net_loss: float


class RiskCalculator:
    """
    Основной класс для расчета риска и позиций.
    Использует конфигурацию трейдинга и адаптивные правила.
    """
    
    def __init__(self, config: Config):
        """
        Инициализация RiskCalculator с конфигурацией.
        :param config: объект Config, содержащий все параметры стратегии и комиссии
        """
        self.config = config
    
    def calculate_position(
        self,
        entry_price: float,
        target_tp_price: Optional[float],
        current_balance: float,
        trade_history: List[Dict[str, Any]],
        suggested_sl_price: Optional[float] = None,
        side: str = "BUY"
    ) -> PositionCalculationResult:
        """
        Основной метод расчета позиции.
        Рассчитывает размер позиции, SL, TP и ожидаемый PnL с учетом истории сделок и адаптивного управления риском.

        :param entry_price: цена входа в позицию
        :param target_tp_price: желаемая цель TP
        :param current_balance: текущий баланс аккаунта
        :param trade_history: список предыдущих сделок (dict с ключами 'success', 'profit' и др.)
        :param suggested_sl_price: желаемый стоп-лосс (если есть)
        :param side: направление сделки ("BUY" или "SELL")
        :return: PositionCalculationResult
        """
        # Проверка корректности цены входа
        if not isinstance(entry_price, (int, float)) or not entry_price > 0:
            raise ValueError(f"Entry price must be a positive number, got: {entry_price}")
        
        # КРИТИЧЕСКАЯ ПРОВЕРКА: логическая согласованность параметров сделки
        if target_tp_price is not None and suggested_sl_price is not None:
            tp_above_entry = target_tp_price > entry_price
            sl_below_entry = suggested_sl_price < entry_price
            
            # Проверяем логическую согласованность с направлением сделки
            if (side == "BUY" and (not tp_above_entry or not sl_below_entry)) or \
               (side == "SELL" and (tp_above_entry or sl_below_entry)):
                raise ValueError(
                    f"Trade parameters are fundamentally inconsistent with {side} direction:\n"
                    f"  Entry: {entry_price}, TP: {target_tp_price}, SL: {suggested_sl_price}\n"
                    f"  Expected for {side}: TP {'>' if side == 'BUY' else '<'} Entry {'>' if side == 'BUY' else '<'} SL\n"
                    f"  Actual relationship: TP {'>' if tp_above_entry else '<'} Entry {'>' if sl_below_entry else '<'} SL\n"
                    f"  This configuration would guarantee a loss regardless of market direction."
                )

        # Максимальный риск в USD для данной сделки
        max_risk_usd = current_balance * self.config.trading.max_risk_per_trade
        total_trades = len(trade_history)
        
        # Если есть достаточно статистики, ограничиваем размер позиции
        if total_trades >= self.config.adaptive.min_trades_for_stats:
            profitable_trades = sum(1 for trade in trade_history if trade.get('success', True))
            current_winrate = profitable_trades / total_trades
            
            # Если текущий винрейт ниже порога, берем минимальный размер позиции
            if current_winrate < self.config.adaptive.winrate_threshold:
                return self._get_minimum_position(entry_price, target_tp_price, side)
        else:
            # Если статистики мало, минимальный размер позиции
            return self._get_minimum_position(entry_price, target_tp_price, side)

        # Сценарий 1: заданы и SL, и TP
        if suggested_sl_price is not None and target_tp_price is not None:
            position_size_usd = self._calculate_size_from_risk(entry_price, suggested_sl_price, max_risk_usd)
            sl_price = suggested_sl_price
            final_tp_price = target_tp_price

        # Сценарий 2: задан только TP
        elif target_tp_price is not None:
            # Рассчитываем необходимый убыток для достижения заданного R/R
            _, _, single_usd_profit, _ = self._calculate_net_pnl(entry_price, target_tp_price, 0, 1.0, side)
            required_net_loss = abs(single_usd_profit / self.config.trading.risk_reward_ratio)
            
            fee_percent = self.config.fees.entry_fee + self.config.fees.tp_fee
            price_loss_percent = required_net_loss - fee_percent
            if price_loss_percent <= 0:
                raise ValueError(
                    f"Cannot achieve target R/R because required price loss ({price_loss_percent:.4%}) is covered by fees ({fee_percent:.4%})."
                )

            # Рассчитываем SL исходя из направления сделки
            sl_delta = entry_price * price_loss_percent
            if side == "BUY":
                sl_price = entry_price - sl_delta
            else:
                sl_price = entry_price + sl_delta
            
            position_size_usd = self._calculate_size_from_risk(entry_price, sl_price, max_risk_usd)
            final_tp_price = target_tp_price

        # Сценарий 3: адаптивный режим без TP и SL
        else:
            position_size_usd = self.calculate_adaptive_position_size(trade_history, current_balance)
            max_allowed_size = current_balance * self.config.trading.max_position_multiplier
            position_size_usd = min(position_size_usd, max_allowed_size)
            
            total_fee_percent = self.config.fees.entry_fee + self.config.fees.sl_fee
            risk_per_position_percent = max_risk_usd / position_size_usd if position_size_usd > 0 else 0
            price_risk_percent = risk_per_position_percent - total_fee_percent

            if price_risk_percent <= 0:
                raise ValueError(
                    f"Risk budget per position ({risk_per_position_percent:.4%}) is smaller than fees ({total_fee_percent:.4%})."
                )

            # Рассчитываем SL и TP исходя из адаптивного риска
            sl_delta = entry_price * price_risk_percent
            if side == "BUY":
                sl_price = entry_price - sl_delta
                tp_delta = sl_delta * self.config.trading.risk_reward_ratio
                final_tp_price = entry_price + tp_delta
            else:
                sl_price = entry_price + sl_delta
                tp_delta = sl_delta * self.config.trading.risk_reward_ratio
                final_tp_price = entry_price - tp_delta

        # Ограничиваем размер позиции минимумом и максимумом
        max_allowed_size = current_balance * self.config.trading.max_position_multiplier
        position_size_usd = max(self.config.trading.min_trade_usd, min(position_size_usd, max_allowed_size))

        # Расчет реальной прибыли и убытка
        _, _, actual_profit, actual_loss = self._calculate_net_pnl(
            entry_price, final_tp_price, sl_price, position_size_usd, side
        )

        return PositionCalculationResult(
            final_tp_price=final_tp_price,
            sl_price=sl_price,
            position_size_usd=position_size_usd,
            tp_net_profit=actual_profit,
            sl_net_loss=actual_loss,
        )

    # --- Вспомогательные методы ---
    
    def _get_minimum_position(self, entry_price: float, target_tp_price: Optional[float], side: str) -> PositionCalculationResult:
        """
        Возвращает минимальную позицию (min_trade_usd) с расчетом TP/SL.
        Используется, когда винрейт слишком низкий или мало статистики.
        """
        min_size = self.config.trading.min_trade_usd
        if target_tp_price:
            tp_profit_percent = abs(target_tp_price - entry_price) / entry_price
            sl_loss_percent = tp_profit_percent / self.config.trading.risk_reward_ratio
            if side == "BUY":
                sl_price = entry_price - (entry_price * sl_loss_percent)
            else:
                sl_price = entry_price + (entry_price * sl_loss_percent)
            final_tp_price = target_tp_price
        else:
            sl_percent = self.config.trading.default_sl_percent
            tp_percent = sl_percent * self.config.trading.risk_reward_ratio
            if side == "BUY":
                sl_price = entry_price * (1 - sl_percent)
                final_tp_price = entry_price * (1 + tp_percent)
            else:
                sl_price = entry_price * (1 + sl_percent)
                final_tp_price = entry_price * (1 - tp_percent)
                
        _, _, min_profit, min_loss = self._calculate_net_pnl(entry_price, final_tp_price, sl_price, min_size, side)
        
        return PositionCalculationResult(
            final_tp_price=final_tp_price,
            sl_price=sl_price,
            position_size_usd=min_size,
            tp_net_profit=min_profit,
            sl_net_loss=min_loss,
        )

    def _calculate_size_from_risk(self, entry_price: float, sl_price: float, max_risk_usd: float) -> float:
        """
        Рассчитывает размер позиции исходя из допустимого риска на сделку.
        :param entry_price: цена входа
        :param sl_price: цена стоп-лосса
        :param max_risk_usd: максимально допустимый риск в USD
        :return: размер позиции в USD
        """
        if entry_price == sl_price:
            raise ValueError("Entry price and suggested SL price cannot be the same.")
        
        price_risk_percent = abs(entry_price - sl_price) / entry_price if entry_price > 0 else 0
        total_fee_percent = self.config.fees.entry_fee + self.config.fees.sl_fee
        total_risk_percent = price_risk_percent + total_fee_percent

        if total_risk_percent <= 0:
            raise ValueError("Total risk percent is zero or negative, cannot calculate position size.")

        return max_risk_usd / total_risk_percent

    def _calculate_net_pnl(
        self,
        entry_price: float,
        tp_price: float,
        sl_price: float, 
        position_size_usd: float,
        side: str = "BUY"
    ) -> Tuple[float, float, float, float]:
        """
        Рассчитывает чистую прибыль и убыток (net PnL) для заданной позиции.
        :return: tp_price, sl_price, net_profit, net_loss
        """
        if entry_price == 0: return tp_price, sl_price, 0.0, 0.0

        entry = Decimal(str(entry_price))
        tp = Decimal(str(tp_price))
        sl = Decimal(str(sl_price))
        position_size = Decimal(str(position_size_usd))
        
        entry_fee_rate = Decimal(str(self.config.fees.entry_fee))
        tp_fee_rate = Decimal(str(self.config.fees.tp_fee))
        sl_fee_rate = Decimal(str(self.config.fees.sl_fee))
        
        quantity = position_size / entry if entry > 0 else Decimal('0')
        
        # TP расчет с учетом направления сделки
        if side == "BUY":
            gross_profit = quantity * (tp - entry)
        else:  # SELL
            gross_profit = quantity * (entry - tp)
        entry_fee_cost = position_size * entry_fee_rate
        exit_tp_value = quantity * tp
        exit_tp_fee_cost = exit_tp_value * tp_fee_rate
        net_profit = gross_profit - entry_fee_cost - exit_tp_fee_cost
        
        # SL расчет
        if side == "BUY":
            gross_loss_amount = abs(quantity * (entry - sl))
        else:
            gross_loss_amount = abs(quantity * (sl - entry))
        
        exit_sl_value = quantity * sl
        exit_sl_fee_cost = exit_sl_value * sl_fee_rate
        net_loss = -(gross_loss_amount + entry_fee_cost + exit_sl_fee_cost)

        return float(tp), float(sl), float(net_profit), float(net_loss)
    
    def calculate_adaptive_position_size(self, trade_history: List[Dict[str, Any]], current_balance: float) -> float:
        """
        Адаптивный расчет размера позиции исходя из истории сделок.
        Учитывает винрейт, серию выигрышных/проигрышных сделок и динамическую агрессию.
        """
        total_trades = len(trade_history)
        if total_trades < self.config.adaptive.min_trades_for_stats:
            return self.config.trading.min_trade_usd

        valid_trades = [trade for trade in trade_history if 'success' in trade]
        profitable_trades = sum(1 for trade in valid_trades if trade['success'])
        total_valid_trades = len(valid_trades)
        current_winrate = profitable_trades / total_valid_trades if total_valid_trades > 0 else 0
        
        # Если винрейт ниже порога, минимальная позиция
        if current_winrate < self.config.adaptive.winrate_threshold:
            return self.config.trading.min_trade_usd

        # Рассчитываем коэффициент производительности
        performance_score = (current_winrate - self.config.adaptive.winrate_threshold) / (1 - self.config.adaptive.winrate_threshold)
        
        # Рассчитываем доверие к стратегии на основе числа сделок
        confidence_numerator = max(0, total_trades - self.config.adaptive.min_trades_for_stats)
        confidence_denominator = max(1, self.config.adaptive.max_confidence_trades - self.config.adaptive.min_trades_for_stats)
        confidence_weight = (confidence_numerator / confidence_denominator) ** 0.7
        
        # Адаптивная агрессия
        dynamic_aggression = self.config.adaptive.min_aggression + (self.config.adaptive.max_aggression - self.config.adaptive.min_aggression) * confidence_weight
        
        core_multiplier = 1.0 + performance_score * dynamic_aggression
        
        # Множитель для серии побед и штраф за серию проигрышей
        winning_streak = 0
        for trade in reversed(valid_trades):
            if trade['success']: winning_streak += 1
            else: break
            
        losing_streak = 0
        for trade in reversed(valid_trades):
            if not trade['success']: losing_streak += 1
            else: break

        winstreak_multiplier = 1.0 + pow(winning_streak, 1.4) * 0.15
        losestreak_penalty = pow(self.config.adaptive.losing_streak_penalty, losing_streak)

        # Итоговый расчет позиции
        base_size = current_balance * self.config.adaptive.base_percent_of_balance
        calculated_size = base_size * core_multiplier * winstreak_multiplier * losestreak_penalty
        
        return calculated_size
