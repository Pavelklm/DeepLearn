"""
Базовые тесты для RiskCalculator.
Тестируем основные сценарии работы.
"""
import pytest
import os
import logging
import sys

# Добавляем путь к модулям, чтобы тесты могли найти модули
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from risk_calculator import RiskCalculator, PositionCalculationResult
from config_manager import Config, TradingConfig, FeesConfig, AdaptiveConfig, ValidationConfig, BacktestReportingConfig, SummaryThresholds, EmojiThresholds

# Настройка логирования для тестов
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# =============================================================================
# fixtures (Фикстуры) - Наша подготовительная база
# =============================================================================

@pytest.fixture(scope="module")
def base_config() -> Config:
    """Создает базовый объект конфигурации один раз для всех тестов."""
    logger.info("----------- СОЗДАНИЕ БАЗОВОГО КОНФИГА (ОДИН РАЗ) -----------")
    trading_conf = TradingConfig(
        max_risk_per_trade=0.01, # 1%
        risk_reward_ratio=3.0,
        initial_balance=10000.0,
        max_daily_drawdown=0.05,
        max_losing_days=3,
        min_trade_usd=10.0,
        max_position_multiplier=3.0,
        max_consecutive_losses_per_day=3,
        default_sl_percent=0.02
    )
    fees_conf = FeesConfig(entry_fee=0.001, tp_fee=0.001, sl_fee=0.001) # 0.1%
    adaptive_conf = AdaptiveConfig(
        min_trades_for_stats=20,
        max_confidence_trades=100,
        winrate_threshold=0.33,
        min_aggression=0.5,
        max_aggression=1.5,
        base_percent_of_balance=0.01,
        losing_streak_penalty=0.8
    )
    # ... остальные конфиги с дефолтными значениями
    validation_conf = ValidationConfig(min_profit_target_pct=0.001, max_profit_target_pct=0.5)
    summary_conf = SummaryThresholds(excellent_return_pct=0.1, good_return_pct=0.0, poor_return_pct=-0.05)
    emoji_conf = EmojiThresholds(winrate_fire=0.6, drawdown_low=0.01, winrate_good=0.4, loss_streak_alert=3, loss_streak_warning=1, drawdown_high=0.03, drawdown_medium=0.01)
    backtest_conf = BacktestReportingConfig(summary_thresholds=summary_conf, emoji_thresholds=emoji_conf)

    return Config(
        binance_api_key='test_key', binance_api_secret='test_secret',
        telegram_token='test_token', telegram_chat_id='test_chat_id',
        trading=trading_conf, fees=fees_conf, adaptive=adaptive_conf,
        validation=validation_conf, backtest_reporting=backtest_conf
    )

@pytest.fixture
def empty_trade_history() -> list:
    """Возвращает пустую историю сделок."""
    return []

# =============================================================================
# Тесты RiskCalculator
# =============================================================================

class TestRiskCalculator:
    """Группируем все тесты для класса RiskCalculator."""

    def test_initialization(self, base_config):
        """✅ ТЕСТ: Корректная инициализация калькулятора."""
        logger.info("ТЕСТ_СТАРТ: Инициализация")
        # WHEN
        calculator = RiskCalculator(base_config)
        # THEN
        assert calculator.config is not None
        assert calculator.config.trading.risk_reward_ratio == 3.0
        logger.info("ТЕСТ_УСПЕШНЫЙ: Калькулятор инициализирован ✓")

    # --- Сценарий 1: Приоритет SL ---
    def test_scenario_1_technical_stop_long(self, base_config, empty_trade_history):
        """✅ СЦЕНАРИЙ 1 (LONG): Расчет размера позиции от заданного SL."""
        logger.info("ТЕСТ_СТАРТ: Сценарий 1 (LONG) - приоритет SL")
        # GIVEN: Калькулятор, баланс и технически обоснованный SL
        calculator = RiskCalculator(base_config)
        balance = 10000.0
        entry_price = 50000.0
        target_tp_price = 54000.0 
        suggested_sl_price = 49000.0 
        
        # ✨ ОБНОВЛЕННАЯ ЛОГИКА РАСЧЕТА ДЛЯ ТЕСТА:
        # Максимальный риск в USD = 1% от 10000 = $100
        # Процент ценового риска = (50000-49000)/50000 = 0.02 (2%)
        # Процент комиссий = 0.001 (вход) + 0.001 (выход) = 0.002 (0.2%)
        # Общий процент риска = 0.02 + 0.002 = 0.022
        # Размер позиции = $100 / 0.022 = $4545.45
        
        logger.info(f"GIVEN: Баланс=${balance}, Вход={entry_price}, TP={target_tp_price}, SL={suggested_sl_price}")
        
        # WHEN
        result = calculator.calculate_position(
            entry_price, target_tp_price, balance, empty_trade_history, suggested_sl_price, "BUY"
        )
        
        # THEN
        logger.info(f"THEN: Получен результат -> {result}")
        # ✨ ИСПРАВЛЕНО: Ожидаем меньший размер позиции из-за учета комиссий
        assert result.position_size_usd == pytest.approx(4545.45, rel=1e-4)
        assert result.sl_price == suggested_sl_price
        assert result.final_tp_price == target_tp_price
        # Проверяем, что реальный убыток действительно около 1% от баланса
        assert abs(result.sl_net_loss) == pytest.approx(100, rel=0.01) # допуск 1%


    # --- Сценарий 2: Приоритет TP ---
    def test_scenario_2_target_profit_long(self, base_config, empty_trade_history):
        """✅ СЦЕНАРИЙ 2 (LONG): Расчет SL и размера от заданного TP."""
        logger.info("ТЕСТ_СТАРТ: Сценарий 2 (LONG) - приоритет TP")
        # GIVEN: Стратегия дала вход и цель, но не стоп
        calculator = RiskCalculator(base_config)
        balance = 10000.0
        entry_price = 60000.0
        target_tp_price = 63000.0 
        
        logger.info(f"GIVEN: Баланс=${balance}, Вход={entry_price}, TP={target_tp_price}, SL не задан.")
        
        # WHEN
        result = calculator.calculate_position(
            entry_price, target_tp_price, balance, empty_trade_history, None, "BUY"
        )
        
        # THEN
        logger.info(f"THEN: Получен результат -> {result}")
        assert result.sl_price == pytest.approx(59161.0, rel=1e-4)
        # ✅ ИСПРАВЛЕНИЕ: Ожидаем корректный размер позиции, рассчитанный на основе чистого PnL
        assert result.position_size_usd == pytest.approx(6256.517, rel=1e-4) 
        assert abs(result.sl_net_loss) == pytest.approx(100, rel=0.01)
        assert result.tp_net_profit == pytest.approx(300, rel=0.03) # Прибыль ~300 (R/R ~ 1:3)

    # --- Сценарий 3: Адаптивный режим ---
    def test_scenario_3_adaptive_no_history(self, base_config, empty_trade_history):
        """✅ СЦЕНАРИЙ 3: Адаптивный режим при пустой истории."""
        logger.info("ТЕСТ_СТАРТ: Сценарий 3 - пустая история")
        # GIVEN
        calculator = RiskCalculator(base_config)
        
        # WHEN
        result = calculator.calculate_position(50000, None, 10000, empty_trade_history, None, "BUY")

        # THEN
        # Должен вернуться минимальный размер, так как сделок меньше `min_trades_for_stats`
        assert result.position_size_usd == base_config.trading.min_trade_usd
        logger.info(f"THEN: Размер позиции {result.position_size_usd}, ожидался минимальный.")

    def test_scenario_3_adaptive_good_history(self, base_config):
        """✅ СЦЕНАРИЙ 3: Адаптивный режим с хорошей историей."""
        logger.info("ТЕСТ_СТАРТ: Сценарий 3 - хорошая история")
        # GIVEN: 30 побед, 10 поражений (winrate 75%)
        calculator = RiskCalculator(base_config)
        # ✅ ИСПРАВЛЕНИЕ: Данные теперь отражают хорошую историю без длинной серии поражений в конце
        good_history = ([{'success': True}, {'success': False}] * 5) + ([{'success': True}] * 30)

        # WHEN
        result = calculator.calculate_position(50000, None, 10000, good_history, None, "BUY")

        # THEN
        # Ожидаем, что размер будет больше базового (1% от баланса = $100)
        assert result.position_size_usd > 100
        logger.info(f"THEN: Размер позиции {result.position_size_usd}, что больше базового.")


    def test_zero_entry_price_raises_error(self, base_config):
        """❌ ТЕСТ: Нулевая цена входа должна вызывать ошибку."""
        logger.info("ТЕСТ_СТАРТ: Обработка нулевой цены входа")
        calculator = RiskCalculator(base_config)
        with pytest.raises(ValueError, match="Entry price must be a positive number"):
            calculator.calculate_position(0, 100, 10000, [], None, "BUY")
        logger.info("ТЕСТ_УСПЕШНЫЙ: ValueError корректно вызван ✓")
        
