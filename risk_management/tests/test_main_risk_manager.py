"""
Комплексные, исчерпывающие и параноидальные тесты для RiskManager.
Тестируем все режимы, все функции и все возможные сценарии отказов.
"""
import pytest
import os
import logging
import json
import time
from unittest.mock import patch, MagicMock, call, ANY
from copy import deepcopy
import sys

# Добавляем путь к модулям, чтобы тесты могли найти модули
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from main_risk_manager import RiskManager
from config_manager import Config, ConfigValidationError, TradingConfig, FeesConfig, AdaptiveConfig, ValidationConfig, BacktestReportingConfig, SummaryThresholds, EmojiThresholds
from risk_calculator import PositionCalculationResult

# Настройка логирования для тестов
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# =============================================================================
# Фикстуры - Наша подготовительная база
# =============================================================================

@pytest.fixture(scope="module")
def real_config():
    """
    Загружает реальный config.json и .env один раз для всех тестов в модуле.
    Это дает нам реалистичную базовую конфигурацию.
    """
    logger.info("----------- ЗАГРУЗКА РЕАЛЬНОГО КОНФИГА (ОДИН РАЗ) -----------")
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config.json')
    # Убеждаемся, что .env файл существует рядом с config.json
    dotenv_path = os.path.join(os.path.dirname(config_path), '.env')
    if not os.path.exists(dotenv_path):
        # Создаем фейковый .env для тестов, если его нет
        with open(dotenv_path, 'w') as f:
            f.write("BINANCE_API_KEY=test_key_from_fixture\n")
            f.write("BINANCE_API_SECRET=test_secret_from_fixture\n")
            f.write("TELEGRAM_TOKEN=12345:ABCDE\n")
            f.write("TELEGRAM_CHAT_ID=123456789\n")
    
    # Используем реальный ConfigManager для загрузки
    from config_manager import ConfigManager
    config = ConfigManager.load_config(config_path)
    logger.info("----------- РЕАЛЬНЫЙ КОНФИГ ЗАГРУЖЕН УСПЕШНО -----------")
    return config


@pytest.fixture
def mock_dependencies(mocker):
    """
    Главная фикстура, которая мокает ВСЕ внешние зависимости RiskManager.
    Это дает нам полный контроль над поведением системы.
    """
    logger.debug("--- Создание моков для зависимостей ---")
    
    # Мокаем все классы, которые RiskManager импортирует и создает
    # autospec=True заставляет моки иметь такую же сигнатуру, как и реальные классы
    mock_binance_client = mocker.patch('main_risk_manager.BinanceClient', autospec=True)
    mock_risk_calculator = mocker.patch('main_risk_manager.RiskCalculator', autospec=True)
    mock_performance_tracker = mocker.patch('main_risk_manager.PerformanceTracker', autospec=True)
    mock_telegram_notifier = mocker.patch('main_risk_manager.TelegramNotifier', autospec=True)
    
    # ConfigManager больше не мокаем - передаем конфиг напрямую в конструктор

    # Возвращаем словарь с моками для удобного доступа в тестах
    mocks = {
        "BinanceClient": mock_binance_client,
        "RiskCalculator": mock_risk_calculator,
        "PerformanceTracker": mock_performance_tracker,
        "TelegramNotifier": mock_telegram_notifier,
    }
    logger.debug("--- Моки для зависимостей созданы ---")
    return mocks


# =============================================================================
# Тесты RiskManager
# =============================================================================

class TestRiskManager:
    """Группируем все тесты для класса RiskManager."""

    # -------------------------------------------------------------------------
    # Тесты инициализации (`__init__`)
    # -------------------------------------------------------------------------

    def test_initialization_backtest_mode(self, mock_dependencies, real_config, capsys):
        """✅ ТЕСТ: Инициализация в режиме 'backtest'."""
        # GIVEN: У нас есть конфиг и моки
        logger.info("ТЕСТ_СТАРТ: test_initialization_backtest_mode")
        
        # WHEN: Инициализируем RiskManager в режиме 'backtest'
        manager = RiskManager(real_config, mock_dependencies['PerformanceTracker'].return_value, mode='backtest')

        # THEN: Проверяем, что все настроено правильно для бектеста
        assert manager.mode == 'backtest'
        assert manager.silent_mode is True
        
        # BinanceClient не должен создаваться
        mock_dependencies['BinanceClient'].assert_not_called()
        logger.info("ПРОВЕРКА: BinanceClient не создан (ожидаемо).")

        # Другие зависимости должны быть созданы
        mock_dependencies['RiskCalculator'].assert_called_once_with(real_config)
        # PerformanceTracker передается в конструктор напрямую, поэтому не создается
        mock_dependencies['TelegramNotifier'].assert_called_once_with(real_config)
        logger.info("ПРОВЕРКА: Все основные зависимости инициализированы.")

        # Заголовок бектеста теперь выводится в других компонентах
        logger.info("ПРОВЕРКА: Логика заголовка перенесена в отчетность.")
        # Проверяем, что никаких ошибок не возникло
        captured = capsys.readouterr()
        assert captured.err == ""  # Нет ошибок

        # Telegram не должен ничего отправлять при старте в silent_mode
        mock_dependencies['TelegramNotifier'].return_value.notify_system_status.assert_not_called()
        logger.info("ПРОВЕРКА: Telegram уведомление о старте не отправлено (ожидаемо).")
        logger.info("ТЕСТ_УСПЕШЕН: Инициализация в режиме 'backtest' корректна ✓")


    def test_initialization_live_mode(self, mock_dependencies, real_config):
        """✅ ТЕСТ: Инициализация в режиме 'live'."""
        # GIVEN: Конфиг и моки
        logger.info("ТЕСТ_СТАРТ: test_initialization_live_mode")

        # WHEN: Инициализируем RiskManager в режиме 'live'
        manager = RiskManager(real_config, mock_dependencies['PerformanceTracker'].return_value, mode='live')

        # THEN: Проверяем настройки для реальной торговли
        assert manager.mode == 'live'
        assert manager.silent_mode is False
        
        # BinanceClient должен быть создан с ключами из конфига
        mock_dependencies['BinanceClient'].assert_called_once_with(
            real_config.binance_api_key, real_config.binance_api_secret
        )
        logger.info("ПРОВЕРКА: BinanceClient создан с API ключами.")

        # Telegram должен отправить уведомление о старте
        mock_dependencies['TelegramNotifier'].return_value.notify_system_status.assert_called_once_with(
            "started", "Система риск-менеджмента запущена в режиме live"
        )
        logger.info("ПРОВЕРКА: Отправлено уведомление в Telegram о запуске.")
        logger.info("ТЕСТ_УСПЕШЕН: Инициализация в режиме 'live' корректна ✓")


    def test_initialization_config_not_found(self):
        """❌ ТЕСТ: Инициализация с несуществующим файлом конфигурации."""
        logger.info("ТЕСТ_СТАРТ: test_initialization_config_not_found")
        
        # GIVEN: Мы знаем, что файла 'non_existent_config.json' не существует
        # WHEN/THEN: Ожидаем, что ConfigManager выбросит исключение ConfigValidationError
        with pytest.raises(ConfigValidationError) as exc_info:
            from config_manager import ConfigManager
            ConfigManager.load_config('non_existent_config.json')
        
        assert "Файл конфигурации не найден" in str(exc_info.value)
        logger.info(f"ПРОВЕРКА: Получено ожидаемое исключение: {exc_info.value}")
        logger.info("ТЕСТ_УСПЕШЕН: Обработка отсутствующего конфига работает ✓")

    # -------------------------------------------------------------------------
    # Тесты управления состоянием (state management)
    # -------------------------------------------------------------------------
    
    def test_state_file_management(self, mock_dependencies, real_config, tmp_path):
        """✅ ТЕСТ: Создание, загрузка и сохранение файла состояния."""
        logger.info("ТЕСТ_СТАРТ: test_state_file_management")
        # GIVEN: Временная директория для тестов
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps({
            "trading": {"initial_balance": 500},
            # ... другие обязательные поля ...
            "fees": {}, "adaptive": {}, "validation": {},
            "backtest_reporting": {"summary_thresholds": {}, "emoji_thresholds": {}}
        }))

        # WHEN: Инициализируем в режиме 'paper', который использует файлы состояния
        mock_config = deepcopy(real_config)
        mock_config.trading.initial_balance = 500
        
        manager = RiskManager(mock_config, mock_dependencies['PerformanceTracker'].return_value, mode='paper')
        manager.state_file = str(tmp_path / "config_paper.json")
        manager._init_state_file()  # Принудительно создаем файл

        state_file_path = tmp_path / "config_paper.json"
        logger.info(f"ПРОВЕРКА: Ожидаемый путь к файлу состояния: {state_file_path}")
        
        # THEN: Проверяем, что файл был создан с начальным состоянием
        assert state_file_path.exists()
        with open(state_file_path, 'r') as f:
            state = json.load(f)
        assert state['balance'] == 500
        assert state['active_trades'] == {}
        logger.info("ПРОВЕРКА: Файл состояния создан с корректным начальным балансом.")

        # WHEN: Изменяем состояние и сохраняем его
        new_state = {"balance": 450.5, "active_trades": {"trade1": {"symbol": "BTCUSDT"}}}
        manager._save_state(new_state)
        logger.info(f"СОХРАНЕНИЕ: Сохранено новое состояние: {new_state}")

        # THEN: Проверяем, что загруженное состояние соответствует сохраненному
        loaded_state = manager._load_state()
        assert loaded_state['balance'] == 450.5
        assert loaded_state['active_trades']["trade1"]["symbol"] == "BTCUSDT"
        logger.info("ПРОВЕРКА: Новое состояние успешно загружено.")
        logger.info("ТЕСТ_УСПЕШЕН: Управление файлом состояния работает корректно ✓")


    def test_load_state_corrupted_json(self, mock_dependencies, real_config, tmp_path):
        """❌ ТЕСТ: Загрузка состояния из поврежденного JSON файла."""
        logger.info("ТЕСТ_СТАРТ: test_load_state_corrupted_json")
        # GIVEN: Поврежденный файл состояния
        config_path = tmp_path / "config.json"
        config_path.touch()
        state_file_path = tmp_path / "config_paper.json"
        state_file_path.write_text("{'balance': 1000, 'oops': }") # Невалидный JSON
        logger.warning(f"СОЗДАНО: Поврежденный файл состояния: {state_file_path.read_text()}")

        # WHEN: Инициализируем менеджер
        manager = RiskManager(real_config, mock_dependencies['PerformanceTracker'].return_value, mode='paper')
        manager.state_file = str(state_file_path)
        
        # THEN: Он должен загрузить начальное состояние вместо поврежденного
        state = manager._load_state()
        assert state['balance'] == real_config.trading.initial_balance
        logger.info("ПРОВЕРКА: Загружено начальное состояние по умолчанию.")
        logger.info("ТЕСТ_УСПЕШЕН: Обработка поврежденного JSON файла корректна ✓")


    # -------------------------------------------------------------------------
    # Тесты основных функций
    # -------------------------------------------------------------------------
    
    def test_get_balance(self, mock_dependencies, real_config):
        """✅ ТЕСТ: Получение баланса в разных режимах."""
        logger.info("ТЕСТ_СТАРТ: test_get_balance")
        
        # Сценарий 1: Режим 'live'
        mock_dependencies['BinanceClient'].return_value.get_account_balance.return_value = 1234.56
        manager_live = RiskManager(real_config, mock_dependencies['PerformanceTracker'].return_value, mode='live')
        
        balance_live = manager_live.get_balance()
        assert balance_live == 1234.56
        mock_dependencies['BinanceClient'].return_value.get_account_balance.assert_called_once_with("USDT")
        logger.info("ПРОВЕРКА (live): Баланс получен из мока BinanceClient.")

        # Сценарий 2: Режим 'paper' (чтение из файла)
        manager_paper = RiskManager(real_config, mock_dependencies['PerformanceTracker'].return_value, mode='paper')
        
        with patch.object(manager_paper, '_load_state', return_value={"balance": 987.65}):
            balance_paper = manager_paper.get_balance()
        assert balance_paper == 987.65
        logger.info("ПРОВЕРКА (paper): Баланс получен из мока файла состояния.")
        logger.info("ТЕСТ_УСПЕШЕН: Получение баланса работает в обоих режимах ✓")


    def test_check_trading_allowed(self, mock_dependencies, real_config):
        """✅/❌ ТЕСТ: Проверка разрешения на торговлю."""
        logger.info("ТЕСТ_СТАРТ: test_check_trading_allowed")
        manager = RiskManager(real_config, mock_dependencies['PerformanceTracker'].return_value, mode='paper')

        # Сценарий 1: Все хорошо, торговля разрешена
        mock_tracker = mock_dependencies['PerformanceTracker'].return_value
        mock_tracker.check_risk_limits.return_value = {'trade_allowed': True, 'reasons': []}
        with patch.object(manager, 'get_balance', return_value=1000):
            result = manager.check_trading_allowed()
        assert result['trade_allowed'] is True
        logger.info("ПРОВЕРКА (OK): Торговля разрешена.")

        # Сценарий 2: Нулевой баланс
        with patch.object(manager, 'get_balance', return_value=0):
            result = manager.check_trading_allowed()
        assert result['trade_allowed'] is False
        assert "Недостаточный баланс" in result['reasons']
        logger.info("ПРОВЕРКА (Zero Balance): Торговля запрещена.")

        # Сценарий 3: Превышена дневная просадка
        mock_tracker.check_risk_limits.return_value = {
            'trade_allowed': False, 
            'reasons': ['Превышена дневная просадка']
        }
        with patch.object(manager, 'get_balance', return_value=1000):
            result = manager.check_trading_allowed()
        assert result['trade_allowed'] is False
        assert 'Превышена дневная просадка' in result['reasons']
        logger.info("ПРОВЕРКА (Drawdown): Торговля запрещена.")
        logger.info("ТЕСТ_УСПЕШЕН: Логика разрешения на торговлю работает корректно ✓")


    def test_execute_trade_success_and_fail_scenarios(self, mock_dependencies, real_config, tmp_path):
        """✅/❌ ТЕСТ: Исполнение сделки - успех и различные сценарии отказа."""
        logger.info("ТЕСТ_СТАРТ: test_execute_trade_scenarios")
        
        # GIVEN: Настраиваем менеджер в режиме 'paper'
        manager = RiskManager(real_config, mock_dependencies['PerformanceTracker'].return_value, mode='paper')
        manager.state_file = str(tmp_path / "config_paper.json")

        # Настраиваем моки для успешной сделки
        mock_perf_tracker = mock_dependencies['PerformanceTracker'].return_value
        mock_perf_tracker.trade_history = []
        mock_risk_calc = mock_dependencies['RiskCalculator'].return_value
        mock_risk_calc.calculate_position.return_value = PositionCalculationResult(
            final_tp_price=52000, sl_price=49000, position_size_usd=100, 
            tp_net_profit=40, sl_net_loss=-20
        )
        
        # Сценарий 1: Успешное исполнение LONG сделки
        logger.info("--- СЦЕНАРИЙ 1: Успешная LONG сделка ---")
        with patch.object(manager, 'check_trading_allowed', return_value={'trade_allowed': True}):
            result = manager.execute_trade(entry_price=50000, target_tp_price=51000)
        
        assert result['trade_allowed'] is True
        assert result['order_placed'] is True
        assert 'order_id' in result
        assert result['side'] == 'BUY'
        assert result['position_size_usd'] == 100
        assert len(manager.active_trades) == 1
        logger.info(f"ПРОВЕРКА (Success): Сделка {result['order_id']} создана и активна.")
        
        # Сценарий 2: Отказ из-за запрета на торговлю
        logger.info("--- СЦЕНАРИЙ 2: Отказ (торговля запрещена) ---")
        with patch.object(manager, 'check_trading_allowed', return_value={'trade_allowed': False, 'reasons': ['Test reason']}):
            result = manager.execute_trade(entry_price=50000, target_tp_price=51000)

        assert result['trade_allowed'] is False
        assert result['reason'] == 'Test reason'
        assert len(manager.active_trades) == 1 # Количество не изменилось
        logger.info("ПРОВЕРКА (Disallowed): Сделка корректно отклонена.")

        # Сценарий 3: Отказ из-за невалидных параметров
        logger.info("--- СЦЕНАРИЙ 3: Отказ (невалидные параметры) ---")
        with patch.object(manager, 'check_trading_allowed', return_value={'trade_allowed': True}):
            result = manager.execute_trade(entry_price=-50, target_tp_price=51000)

        assert result['trade_allowed'] is False
        assert 'Entry price must be a positive number' in result['reason']
        logger.info("ПРОВЕРКА (Invalid Params): Сделка корректно отклонена из-за валидации.")
        logger.info("ТЕСТ_УСПЕШЕН: Все сценарии исполнения сделки отработали ✓")


    def test_update_trade_result_profit_and_loss(self, mock_dependencies, real_config, tmp_path):
        """✅/❌ ТЕСТ: Обновление результатов сделки (прибыль и убыток)."""
        logger.info("ТЕСТ_СТАРТ: test_update_trade_result_profit_and_loss")
        
        # GIVEN: Менеджер с активной сделкой
        initial_balance = 10000.0
        mock_config = deepcopy(real_config)
        mock_config.trading.initial_balance = initial_balance
        
        manager = RiskManager(mock_config, mock_dependencies['PerformanceTracker'].return_value, mode='paper')
        manager.state_file = str(tmp_path / "config_paper.json")

        order_id = "test_trade_1"
        manager.active_trades[order_id] = {
            "symbol": "BTCUSDT", "entry_price": 50000.0,
            "quantity": 0.02, "side": "BUY", "timestamp": "..."
        }
        manager._save_state({"balance": initial_balance, "active_trades": manager.active_trades})
        
        # Сценарий 1: Прибыльное закрытие
        logger.info("--- СЦЕНАРИЙ 1: Прибыльное закрытие ---")
        result = manager.update_trade_result(order_id, exit_price=51000, trade_type="TP")

        assert result['success'] is True
        # PnL = 0.02 * (51000 - 50000) = 20.
        # Допустим, комиссии из конфига составляют 0.1%
        # entry_fee = (50000 * 0.02) * 0.001 = 1. 
        # exit_fee = (51000 * 0.02) * 0.001 = 1.02. 
        # Net profit ~ 20 - 1 - 1.02 = 17.98
        assert result['profit'] == pytest.approx(17.98) 
        assert len(manager.active_trades) == 0
        new_balance = manager.get_balance()
        assert new_balance == pytest.approx(initial_balance + 17.98)
        logger.info(f"ПРОВЕРКА (Profit): Сделка закрыта с прибылью, баланс обновлен до {new_balance:.2f}")
        mock_dependencies['PerformanceTracker'].return_value.update_trade_statistics.assert_called()

        # Сценарий 2: Убыточное закрытие
        logger.info("--- СЦЕНАРИЙ 2: Убыточное закрытие ---")
        order_id_2 = "test_trade_2"
        manager.active_trades[order_id_2] = {
            "symbol": "BTCUSDT", "entry_price": 50000.0,
            "quantity": 0.02, "side": "BUY", "timestamp": "..."
        }
        manager._save_state({"balance": new_balance, "active_trades": manager.active_trades})

        result = manager.update_trade_result(order_id_2, exit_price=49500, trade_type="SL")
        
        assert result['success'] is False
        # PnL = 0.02 * (49500 - 50000) = -10.
        # entry_fee = 1. exit_fee = (49500 * 0.02) * 0.001 = 0.99.
        # Net profit ~ -10 - 1 - 0.99 = -11.99
        assert result['profit'] == pytest.approx(-11.99)
        final_balance = manager.get_balance()
        assert final_balance == pytest.approx(new_balance - 11.99)
        logger.info(f"ПРОВЕРКА (Loss): Сделка закрыта с убытком, баланс обновлен до {final_balance:.2f}")

        # Сценарий 3: Несуществующий order_id
        result = manager.update_trade_result("non_existent_id", 50000)
        assert result['success'] is False
        assert result['reason'] == "Trade not found"
        logger.info("ПРОВЕРКА (Invalid ID): Попытка закрыть несуществующую сделку обработана.")
        logger.info("ТЕСТ_УСПЕШЕН: Обновление результатов сделок работает корректно ✓")

