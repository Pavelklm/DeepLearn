"""
Модуль расчета риска и позиций
Версия 3.0: Исправлены фундаментальные ошибки в логике Сценария 2 и 3.
Все расчеты теперь учитывают комиссии для достижения точного R/R и риск-лимитов.
"""
import logging
from typing import Dict, Any, List, Tuple, Optional
from dataclasses import dataclass
from decimal import Decimal, getcontext, ROUND_HALF_UP
from .config_manager import Config

# Устанавливаем финансовую точность
getcontext().prec = 18
getcontext().rounding = ROUND_HALF_UP


logger = logging.getLogger(__name__)


@dataclass
class PositionCalculationResult:
    """Результат расчета позиции"""
    final_tp_price: float
    sl_price: float
    position_size_usd: float
    tp_net_profit: float
    sl_net_loss: float


class RiskCalculator:
    """Калькулятор риска и размера позиций"""
    
    def __init__(self, config: Config):
        self.config = config
        logger.info("Калькулятор риска инициализирован")
    
    def calculate_position(self,
                           entry_price: float,
                           target_tp_price: Optional[float],
                           current_balance: float,
                           trade_history: List[Dict[str, Any]],
                           suggested_sl_price: Optional[float] = None) -> PositionCalculationResult:
        """
        Главный расчет позиции. Логика зависит от предоставленных стратегией данных.
        """
        logger.info("="*50)
        logger.info(f"НАЧИНАЕМ РАСЧЕТ ПОЗИЦИИ (Баланс: ${current_balance:,.2f})")
        logger.info(f"  Вход: {entry_price}, Целевой TP: {target_tp_price}, Предложенный SL: {suggested_sl_price}")

        if not isinstance(entry_price, (int, float)) or not entry_price > 0:
            raise ValueError(f"Entry price must be a positive number, got: {entry_price}")

        position_size_usd: float
        sl_price: float
        final_tp_price: float
        
        max_risk_usd = current_balance * self.config.trading.max_risk_per_trade

        # Проверка статистики для принудительного ограничения размера
        total_trades = len(trade_history)
        if total_trades >= self.config.adaptive.min_trades_for_stats:
            profitable_trades = sum(1 for trade in trade_history if trade.get('success', True))
            current_winrate = profitable_trades / total_trades
            
            if current_winrate < self.config.adaptive.winrate_threshold:
                logger.info(f"ПРИНУДИТЕЛЬНОЕ ОГРАНИЧЕНИЕ: Винрейт {current_winrate:.1%} < {self.config.adaptive.winrate_threshold:.1%}")
                # Рассчитываем минимальные уровни для $10 позиции
                min_size = self.config.trading.min_trade_usd
                if target_tp_price:
                    # Используем переданный TP, вычисляем SL для R/R
                    tp_profit_percent = abs(target_tp_price - entry_price) / entry_price
                    sl_loss_percent = tp_profit_percent / self.config.trading.risk_reward_ratio
                    sl_price = entry_price - (entry_price * sl_loss_percent) if target_tp_price > entry_price else entry_price + (entry_price * sl_loss_percent)
                    final_tp_price = target_tp_price
                else:
                    # Режим автомата - создаем стандартные уровни
                    sl_price = entry_price * 0.98  # 2% SL
                    final_tp_price = entry_price * 1.06  # 6% TP для R/R 3:1
                    
                _, _, min_profit, min_loss = self._calculate_net_pnl(entry_price, final_tp_price, sl_price, min_size)
                
                return PositionCalculationResult(
                    final_tp_price=final_tp_price,
                    sl_price=sl_price,
                    position_size_usd=min_size,
                    tp_net_profit=min_profit,
                    sl_net_loss=min_loss,
                )
        else:
            logger.info(f"ПРИНУДИТЕЛЬНОЕ ОГРАНИЧЕНИЕ: Недостаточно сделок ({total_trades} < {self.config.adaptive.min_trades_for_stats})")
            min_size = self.config.trading.min_trade_usd
            if target_tp_price:
                tp_profit_percent = abs(target_tp_price - entry_price) / entry_price
                sl_loss_percent = tp_profit_percent / self.config.trading.risk_reward_ratio
                sl_price = entry_price - (entry_price * sl_loss_percent) if target_tp_price > entry_price else entry_price + (entry_price * sl_loss_percent)
                final_tp_price = target_tp_price
            else:
                sl_price = entry_price * 0.98
                final_tp_price = entry_price * 1.06
                
            _, _, min_profit, min_loss = self._calculate_net_pnl(entry_price, final_tp_price, sl_price, min_size)
            
            return PositionCalculationResult(
                final_tp_price=final_tp_price,
                sl_price=sl_price,
                position_size_usd=min_size,
                tp_net_profit=min_profit,
                sl_net_loss=min_loss,
            )

        # --- Выбор сценария ---

        if suggested_sl_price is not None and target_tp_price is not None:
            # --- СЦЕНАРИЙ 1: Приоритет Стоп-Лосса ("Технический") ---
            logger.info("СЦЕНАРИЙ 1: Расчет от заданного SL.")
            position_size_usd = self._calculate_size_from_risk(entry_price, suggested_sl_price, max_risk_usd)
            sl_price = suggested_sl_price
            final_tp_price = target_tp_price

        elif target_tp_price is not None:
            # --- СЦЕНАРИЙ 2: Приоритет Тейк-Профита ("Целевой") ---
            logger.info("СЦЕНАРИЙ 2: Расчет от заданного TP и R/R.")
            
            _, _, single_usd_profit, _ = self._calculate_net_pnl(entry_price, target_tp_price, 0, 1.0)
            
            required_net_loss = abs(single_usd_profit / self.config.trading.risk_reward_ratio)
            
            fee_percent = self.config.fees.entry_fee + self.config.fees.sl_fee
            price_loss_percent = required_net_loss - fee_percent
            if price_loss_percent <= 0:
                raise ValueError(f"Cannot achieve target R/R because required price loss ({price_loss_percent:.4%}) is covered by fees ({fee_percent:.4%}).")

            sl_delta = entry_price * price_loss_percent
            sl_price = entry_price - sl_delta if target_tp_price > entry_price else entry_price + sl_delta
            
            position_size_usd = self._calculate_size_from_risk(entry_price, sl_price, max_risk_usd)
            final_tp_price = target_tp_price

        else:
            # --- СЦЕНАРИЙ 3: Полный Автомат ("Адаптивный") ---
            logger.info("СЦЕНАРИЙ 3: Адаптивный расчет размера и уровней.")
            
            position_size_usd = self.calculate_adaptive_position_size(trade_history, current_balance)
            
            total_fee_percent = self.config.fees.entry_fee + self.config.fees.sl_fee
            risk_per_position_percent = max_risk_usd / position_size_usd if position_size_usd > 0 else 0
            price_risk_percent = risk_per_position_percent - total_fee_percent

            if price_risk_percent <= 0:
                 raise ValueError(f"Risk budget per position ({risk_per_position_percent:.4%}) is smaller than fees ({total_fee_percent:.4%}).")

            sl_delta = entry_price * price_risk_percent
            sl_price = entry_price - sl_delta
            
            tp_delta = sl_delta * self.config.trading.risk_reward_ratio
            final_tp_price = entry_price + tp_delta

        # --- Финальные ограничения и расчеты ---
        
        max_allowed_size = current_balance * self.config.trading.max_position_multiplier
        position_size_usd = max(self.config.trading.min_trade_usd, min(position_size_usd, max_allowed_size))
        logger.info(f"Размер позиции после ограничений: ${position_size_usd:.2f}")

        _, _, actual_profit, actual_loss = self._calculate_net_pnl(
            entry_price, final_tp_price, sl_price, position_size_usd
        )

        result = PositionCalculationResult(
            final_tp_price=final_tp_price,
            sl_price=sl_price,
            position_size_usd=position_size_usd,
            tp_net_profit=actual_profit,
            sl_net_loss=actual_loss,
        )

        logger.info(f"ИТОГОВЫЙ РЕЗУЛЬТАТ: {result}")
        logger.info("="*50 + "\n")
        return result

    def _calculate_size_from_risk(self, entry_price: float, sl_price: float, max_risk_usd: float) -> float:
        """Рассчитывает размер позиции, чтобы чистый убыток не превышал max_risk_usd."""
        if entry_price == sl_price:
            raise ValueError("Entry price and suggested SL price cannot be the same.")
        
        price_risk_percent = abs(entry_price - sl_price) / entry_price if entry_price > 0 else 0
        total_fee_percent = self.config.fees.entry_fee + self.config.fees.sl_fee
        total_risk_percent = price_risk_percent + total_fee_percent

        if total_risk_percent <= 0:
            raise ValueError("Total risk percent is zero or negative, cannot calculate position size.")

        return max_risk_usd / total_risk_percent

    def _calculate_net_pnl(self, entry_price: float, tp_price: float, sl_price: float, 
                           position_size_usd: float) -> Tuple[float, float, float, float]:
        """Вспомогательная функция для расчета точных PnL с учетом комиссий."""
        if entry_price == 0: return tp_price, sl_price, 0.0, 0.0

        entry = Decimal(str(entry_price))
        tp = Decimal(str(tp_price))
        sl = Decimal(str(sl_price))
        position_size = Decimal(str(position_size_usd))
        
        entry_fee_rate = Decimal(str(self.config.fees.entry_fee))
        tp_fee_rate = Decimal(str(self.config.fees.tp_fee))
        sl_fee_rate = Decimal(str(self.config.fees.sl_fee))
        
        quantity = position_size / entry if entry > 0 else Decimal('0')
        
        # Расчет для TP
        gross_profit = quantity * (tp - entry)
        entry_fee_cost = position_size * entry_fee_rate
        exit_tp_value = quantity * tp
        exit_tp_fee_cost = exit_tp_value * tp_fee_rate
        net_profit = gross_profit - entry_fee_cost - exit_tp_fee_cost
        
        # Расчет для SL
        gross_loss = quantity * (entry - sl)
        exit_sl_value = quantity * sl
        exit_sl_fee_cost = exit_sl_value * sl_fee_rate
        net_loss = -(gross_loss + entry_fee_cost + exit_sl_fee_cost)

        return float(tp), float(sl), float(net_profit), float(net_loss)
    
    def calculate_adaptive_position_size(self, 
                                     trade_history: List[Dict[str, Any]], 
                                     current_balance: float) -> float:
        """Рассчитывает размер позиции на основе элегантной математической модели."""
        logger.info("\n--- Запуск адаптивной модели расчета размера ---")
        
        total_trades = len(trade_history)
        if total_trades < self.config.adaptive.min_trades_for_stats:
            logger.info(f"Вердикт: Новичок. Размер: ${self.config.trading.min_trade_usd:.2f}")
            return self.config.trading.min_trade_usd

        # ✅ ИСПРАВЛЕНИЕ: Безопасное значение по умолчанию - False
        profitable_trades = sum(1 for trade in trade_history if trade.get('success', False))
        current_winrate = profitable_trades / total_trades if total_trades > 0 else 0
        
        if current_winrate < self.config.adaptive.winrate_threshold:
            logger.info(f"Вердикт: Низкий винрейт. Размер: ${self.config.trading.min_trade_usd:.2f}")
            return self.config.trading.min_trade_usd

        performance_score = (current_winrate - self.config.adaptive.winrate_threshold) / (1 - self.config.adaptive.winrate_threshold)
        
        confidence_numerator = max(0, total_trades - self.config.adaptive.min_trades_for_stats)
        confidence_denominator = max(1, self.config.adaptive.max_confidence_trades - self.config.adaptive.min_trades_for_stats)
        confidence_weight = (confidence_numerator / confidence_denominator) ** 0.7
        
        dynamic_aggression = self.config.adaptive.min_aggression + (self.config.adaptive.max_aggression - self.config.adaptive.min_aggression) * confidence_weight
        
        core_multiplier = 1.0 + performance_score * dynamic_aggression
        
        winning_streak = 0
        for trade in reversed(trade_history):
            if trade.get('success', False): winning_streak += 1
            else: break
            
        losing_streak = 0
        for trade in reversed(trade_history):
            if not trade.get('success', False): losing_streak += 1
            else: break

        winstreak_multiplier = 1.0 + pow(winning_streak, 1.4) * 0.15
        
        # ✅ ИСПРАВЛЕНИЕ: Используем значение из конфига
        losestreak_penalty = pow(self.config.adaptive.losing_streak_penalty, losing_streak)

        base_size = current_balance * self.config.adaptive.base_percent_of_balance
        
        calculated_size = base_size * core_multiplier * winstreak_multiplier * losestreak_penalty
        
        final_size = calculated_size
        
        logger.info(f"Адаптивный размер (до ограничений): ${final_size:,.2f}")
        return final_size