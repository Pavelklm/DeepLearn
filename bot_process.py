# Файл: bot_process.py

import pandas as pd
import importlib
from risk_management.main_risk_manager import RiskManager
from risk_management.config_manager import ConfigManager
from reporting.backtest_reporter import BacktestReporter
from risk_management.performance_tracker import PerformanceTracker

class Playground:
    def __init__(self, bot_config: dict, bot_name: str, ohlcv_data: pd.DataFrame):
        self.bot_config = bot_config
        self.bot_name = bot_name
        self.ohlcv_data = ohlcv_data
        
        self.config = ConfigManager.load_config(bot_config['risk_config_file'])
        self.tracker = PerformanceTracker(self.config)
        self.risk_manager = RiskManager(
            config=self.config,
            performance_tracker=self.tracker,
            mode="backtest"
        )
        self.reporter = BacktestReporter(
            bot_name=self.bot_name,
            tracker=self.tracker,
            initial_balance=self.config.trading.initial_balance
        )
        self.strategy = self._prepare_strategy()

    def _prepare_strategy(self):
        try:
            strategy_file = self.bot_config['strategy_file']
            strategy_module_path = f"strategies.{strategy_file}"
            strategy_module = importlib.import_module(strategy_module_path)
            strategy_params = self.bot_config.get('strategy_params', {})
            return strategy_module.Strategy(**strategy_params)
        except (ImportError, KeyError, AttributeError) as e:
            print(f"❌ Ошибка загрузки стратегии: {e}")
            raise

    def run(self):
        if not self.strategy:
            return

        for i in range(1, len(self.ohlcv_data)):
            historical_data_slice = self.ohlcv_data.iloc[:i]
            # last_candle теперь это Series, представляющая одну строку
            last_candle = self.ohlcv_data.iloc[i-1] 

            # --- ИСПРАВЛЕНИЕ ЗДЕСЬ ---
            # Явно извлекаем ЧИСЛА из ячеек таблицы
            current_high = last_candle['High'].item()
            current_low = last_candle['Low'].item()

            if not self.risk_manager.active_trades:
                signal_info = self.strategy.analyze(historical_data_slice)
                if signal_info and signal_info.get('signal') == 'buy':
                    entry_price = last_candle['Close'].item()
                    
                    self.risk_manager.execute_trade(
                        entry_price=entry_price,
                        target_tp_price=signal_info.get('target_tp_price'),
                        symbol=self.bot_config.get("symbol", "BTC-USD"),
                        timestamp=str(historical_data_slice.index[-1])
                    )
            else:
                order_id = list(self.risk_manager.active_trades.keys())[0]
                active_trade = self.risk_manager.active_trades[order_id]
                tp_price = active_trade.get('tp_price')
                sl_price = active_trade.get('sl_price')
                
                exit_price, exit_type = None, None
                
                # Теперь сравнение происходит между двумя числами, а не числом и Series
                if sl_price and current_low <= sl_price:
                    exit_price, exit_type = sl_price, "SL"
                elif tp_price and current_high >= tp_price:
                    exit_price, exit_type = tp_price, "TP"
                
                if exit_price and exit_type:
                    self.risk_manager.update_trade_result(
                        order_id=order_id,
                        exit_price=exit_price,
                        trade_type=exit_type,
                        timestamp=str(historical_data_slice.index[-1])
                    )
        
        if self.bot_config.get("generate_chart", False):
            self.reporter.generate_report(self.ohlcv_data)