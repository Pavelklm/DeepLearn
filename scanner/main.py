#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Точка входа для рефакторизированного сканера больших ордеров Binance Futures
"""

from cli import CLI


def main():
    """Главная функция"""
    cli = CLI()
    cli.run()


if __name__ == "__main__":
    main()
