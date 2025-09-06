"""Модуль управления конфигурацией"""
import json
import os
from dataclasses import dataclass, fields, is_dataclass
from typing import Any
from dotenv import load_dotenv


class ConfigValidationError(Exception):
    """Кастомная ошибка для проблем валидации конфигурации."""
    pass


# --- Датаклассы для каждой секции ---

@dataclass
class TradingConfig:
    """Конфигурация торговых параметров."""
    risk_reward_ratio: float
    initial_balance: float
    max_daily_drawdown: float
    max_losing_days: int
    min_trade_usd: float
    max_position_multiplier: float
    max_risk_per_trade: float
    max_consecutive_losses_per_day: int
    max_consecutive_losses_global: int
    default_sl_percent: float
    max_concurrent_trades: int  # Максимальное количество одновременных позиций
    max_futures_leverage: float  # Максимальное плечо для фьючерсной торговли (1x-10x)
    # Новые параметры для более гибкой настройки:
    default_tp_percent_for_long: float  # Дефолтный процент прибыли для лонга (0.02 = 2%)
    max_reasonable_profit_multiplier: float  # Множитель для проверки разумности прибыли (10.0 = 1000%)

@dataclass
class FeesConfig:
    """Конфигурация комиссий."""
    entry_fee: float
    tp_fee: float
    sl_fee: float


@dataclass
class AdaptiveConfig:
    """Конфигурация адаптивной системы."""
    min_trades_for_stats: int
    max_confidence_trades: int
    winrate_threshold: float
    min_aggression: float
    max_aggression: float
    base_percent_of_balance: float
    losing_streak_penalty: float
    # Новые параметры для более гибкой настройки:
    winstreak_power: float  # Степень для расчета множителя серии побед (1.4)
    winstreak_multiplier: float  # Множитель для серии побед (0.15)
    confidence_power: float  # Степень для расчета доверия (0.7)


@dataclass
class ValidationConfig:
    """Конфигурация параметров валидации."""
    min_profit_target_pct: float
    max_profit_target_pct: float


@dataclass
class SummaryThresholds:
    """Пороги для текстовых итогов бэктеста."""
    excellent_return_pct: float
    good_return_pct: float
    poor_return_pct: float


@dataclass
class EmojiThresholds:
    """Пороги для эмодзи в отчете бэктеста."""
    winrate_fire: float
    winrate_good: float
    loss_streak_alert: int
    loss_streak_warning: int
    drawdown_high: float
    drawdown_medium: float
    drawdown_low: float

@dataclass
class BacktestReportingConfig:
    """Конфигурация отчетов бэктеста."""
    summary_thresholds: SummaryThresholds
    emoji_thresholds: EmojiThresholds


@dataclass
class Config:
    """Основной датакласс, объединяющий всю конфигурацию."""
    # Секреты из .env
    binance_api_key: str
    binance_api_secret: str
    telegram_token: str
    telegram_chat_id: str
    
    # Параметры из config.json
    trading: TradingConfig
    fees: FeesConfig
    adaptive: AdaptiveConfig
    validation: ValidationConfig
    backtest_reporting: BacktestReportingConfig


class ConfigManager:
    """Менеджер для загрузки и валидации конфигурации."""

    @staticmethod
    def _get_env_var(key: str) -> str:
        """Приватный хелпер для безопасного получения переменных окружения."""
        value = os.getenv(key)
        return value if value is not None else ''

    @staticmethod
    def load_config(config_path: str = "config.json") -> Config:
        """
        Загружает конфигурацию из .env и .json, объединяет и валидирует её.
        """
        load_dotenv()

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                json_config = json.load(f)
        except FileNotFoundError:
            raise ConfigValidationError(f"Файл конфигурации не найден: {config_path}")
        except json.JSONDecodeError as e:
            raise ConfigValidationError(f"Ошибка парсинга JSON в файле {config_path}: {e}")

        env_vars = {
            'binance_api_key': ConfigManager._get_env_var('BINANCE_API_KEY'),
            'binance_api_secret': ConfigManager._get_env_var('BINANCE_API_SECRET'),
            'telegram_token': ConfigManager._get_env_var('TELEGRAM_TOKEN'),
            'telegram_chat_id': ConfigManager._get_env_var('TELEGRAM_CHAT_ID')
        }
        
        try:
            # ✨ ИСПРАВЛЕНО: Явное создание вложенных датаклассов для Pylance
            # Этот подход более "прямолинейный", но полностью понятен для статического анализатора.
            trading_conf = TradingConfig(**json_config['trading'])
            fees_conf = FeesConfig(**json_config['fees'])
            adaptive_conf = AdaptiveConfig(**json_config['adaptive'])
            validation_conf = ValidationConfig(**json_config['validation'])

            # Создаем самые глубоко вложенные объекты отчета
            summary_conf = SummaryThresholds(**json_config['backtest_reporting']['summary_thresholds'])
            emoji_conf = EmojiThresholds(**json_config['backtest_reporting']['emoji_thresholds'])
            
            # Создаем родительский объект для них
            backtest_reporting_conf = BacktestReportingConfig(
                summary_thresholds=summary_conf,
                emoji_thresholds=emoji_conf
            )

            # Собираем финальный объект конфигурации
            config = Config(
                **env_vars,
                trading=trading_conf,
                fees=fees_conf,
                adaptive=adaptive_conf,
                validation=validation_conf,
                backtest_reporting=backtest_reporting_conf
            )
        except (KeyError, TypeError) as e:
            raise ConfigValidationError(f"Ошибка структуры или типа данных в config.json: {e}")

        ConfigManager.validate_config(config)
        return config

    @staticmethod
    def validate_config(config: Config) -> None:
        """
        Проверяет корректность всех загруженных параметров конфигурации.
        """
        # Проверка секретов (убрали дублирование кода)
        required_env_vars = {
            'binance_api_key': 'BINANCE_API_KEY',
            'binance_api_secret': 'BINANCE_API_SECRET',
            'telegram_token': 'TELEGRAM_TOKEN',
            'telegram_chat_id': 'TELEGRAM_CHAT_ID'
        }
        for attr, env_key in required_env_vars.items():
            value = getattr(config, attr)
            if not value or not value.strip():
                raise ConfigValidationError(f"Отсутствует обязательная переменная '{env_key}' в .env файле")

        # Проверка торговых параметров
        if config.trading.risk_reward_ratio <= 0:
            raise ConfigValidationError("risk_reward_ratio должно быть больше 0")
        if config.trading.initial_balance <= 0:
            raise ConfigValidationError("initial_balance должно быть больше 0")
        if not 0 < config.trading.max_daily_drawdown <= 1:
            raise ConfigValidationError("max_daily_drawdown должно быть от 0 до 1")
        if config.trading.max_losing_days < 1:
            raise ConfigValidationError("max_losing_days должно быть больше 0")
        if config.trading.max_consecutive_losses_global < 1:
            raise ConfigValidationError("max_consecutive_losses_global должно быть больше 0")
        if config.trading.max_consecutive_losses_global <= config.trading.max_consecutive_losses_per_day:
            raise ConfigValidationError("max_consecutive_losses_global должно быть больше max_consecutive_losses_per_day")
        if config.trading.min_trade_usd <= 0:
            raise ConfigValidationError("min_trade_usd должно быть больше 0")
        if config.trading.max_position_multiplier <= 0:
            raise ConfigValidationError("max_position_multiplier должно быть больше 0")
        if not 0.001 <= config.trading.default_sl_percent <= 0.1:
            raise ConfigValidationError("default_sl_percent должно быть от 0.1% до 10%")
        if not 0 < config.trading.max_risk_per_trade <= 0.05:
            raise ConfigValidationError("max_risk_per_trade должно быть от 0 до 0.05 (5%)")
        if config.trading.max_concurrent_trades < 1:
            raise ConfigValidationError("max_concurrent_trades должно быть больше 0")
        if config.trading.max_concurrent_trades > 10:
            raise ConfigValidationError("max_concurrent_trades не должно превышать 10 для безопасности")
        if not 1.0 <= config.trading.max_futures_leverage <= 10.0:
            raise ConfigValidationError("max_futures_leverage должно быть от 1.0x до 10.0x для безопасности")
        if not 0.005 <= config.trading.default_tp_percent_for_long <= 0.1:
            raise ConfigValidationError("default_tp_percent_for_long должно быть от 0.5% до 10%")
        if not 5.0 <= config.trading.max_reasonable_profit_multiplier <= 50.0:
            raise ConfigValidationError("max_reasonable_profit_multiplier должно быть от 5x до 50x")

        # Проверяем комиссии
        if not 0 <= config.fees.entry_fee <= 1:
            raise ConfigValidationError("entry_fee должно быть от 0 до 1")
        if not 0 <= config.fees.tp_fee <= 1:
            raise ConfigValidationError("tp_fee должно быть от 0 до 1")
        if not 0 <= config.fees.sl_fee <= 1:
            raise ConfigValidationError("sl_fee должно быть от 0 до 1")

        # Проверяем адаптивные параметры
        if config.adaptive.min_trades_for_stats < 1:
            raise ConfigValidationError("min_trades_for_stats должно быть больше 0")
        if config.adaptive.max_confidence_trades <= config.adaptive.min_trades_for_stats:
            raise ConfigValidationError("max_confidence_trades должно быть больше min_trades_for_stats")
        if not 0 < config.adaptive.winrate_threshold <= 1:
            raise ConfigValidationError("winrate_threshold должно быть от 0 до 1")
        if config.adaptive.min_aggression < 0:
            raise ConfigValidationError("min_aggression должно быть >= 0")
        if config.adaptive.max_aggression <= config.adaptive.min_aggression:
            raise ConfigValidationError("max_aggression должно быть больше min_aggression")
        if not 0 < config.adaptive.base_percent_of_balance <= 0.1:
            raise ConfigValidationError("base_percent_of_balance должно быть от 0 до 0.1 (10%)")
        if not 0 < config.adaptive.losing_streak_penalty <= 1:
            raise ConfigValidationError("losing_streak_penalty должно быть от 0 до 1")
        if not 1.0 <= config.adaptive.winstreak_power <= 2.0:
            raise ConfigValidationError("winstreak_power должно быть от 1.0 до 2.0")
        if not 0.05 <= config.adaptive.winstreak_multiplier <= 0.5:
            raise ConfigValidationError("winstreak_multiplier должно быть от 0.05 до 0.5")
        if not 0.5 <= config.adaptive.confidence_power <= 1.0:
            raise ConfigValidationError("confidence_power должно быть от 0.5 до 1.0")

