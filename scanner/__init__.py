#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Refactored Big Orders Scanner for Binance Futures

Модульная архитектура сканера больших ордеров с персистентным хранением
"""

from .config import ScannerConfig
from .api_client import BinanceAPIClient
from .data_models import OrderData, SymbolMetrics, SymbolData, SymbolResult, OrderKey
from .symbol_manager import SymbolManager
from .metrics_calculator import MetricsCalculator
from .order_analyzer import OrderAnalyzer
from .data_storage import DataStorage
from .scanner import BinanceBigOrdersScanner
from .cli import CLI

__version__ = "2.0.0"
__author__ = "Pavel"

__all__ = [
    "ScannerConfig",
    "BinanceAPIClient", 
    "OrderData",
    "SymbolMetrics",
    "SymbolData", 
    "SymbolResult",
    "OrderKey",
    "SymbolManager",
    "MetricsCalculator",
    "OrderAnalyzer",
    "DataStorage",
    "BinanceBigOrdersScanner",
    "CLI"
]
