#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точка входа для рефакторизированного сканера больших ордеров Binance Futures
"""

import sys
import os

# Add parent directory to path for absolute imports
parent_dir = os.path.dirname(os.path.abspath(__file__))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

try:
    from cli import CLI
except ImportError:
    try:
        from .cli import CLI
    except ImportError:
        # If both fail, try importing from the same directory
        import cli
        CLI = cli.CLI


def main():
    """Главная функция"""
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    main()
