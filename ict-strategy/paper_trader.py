"""Thin wrapper — lógica completa en alpaca_trader.py (root del proyecto)."""
from __future__ import annotations
import os, sys

# Agrega el root del proyecto al path para poder importar alpaca_trader
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from alpaca_trader import AlpacaTrader  # noqa: E402

_HERE            = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_FILE = os.path.join(_HERE, "data", "portfolio.json")
INITIAL_CAPITAL  = 10_000.0


class PaperTrader(AlpacaTrader):
    def __init__(
        self,
        data_file: str = DEFAULT_DATA_FILE,
        initial_capital: float = INITIAL_CAPITAL,
    ):
        super().__init__(data_file=data_file, initial_capital=initial_capital)
