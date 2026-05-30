"""
Breakout 50d — entrada cuando el cierre diario supera por primera vez el máximo de los
últimos 50 días. Trailing stop puro (sin hard target). Usa datos diarios.
Backtest óptimo: +14.5% anual, +89.8% total en 4.7 años.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EXIT = {
    "stop_loss":        -0.06,   # -6%
    "hard_target":       9.99,   # sin hard target (trail puro)
    "trailing_trigger":  0.05,   # trailing activa a +5%
    "trailing_pct":      0.08,   # trail 8% desde pico
    "time_stop_days":    30,     # máx 30 días de trading
}

LOOKBACK = 50   # días


def scan_signals(ticker: str, df: pd.DataFrame) -> list[dict]:
    if len(df) < LOOKBACK + 2:
        return []

    closes = df["Close"].values
    high_series  = pd.Series(closes)

    # Rolling max con shift 1 = máximo de los 50 cierres ANTERIORES a cada barra
    rolling_high = high_series.shift(1).rolling(LOOKBACK).max().values

    signals = []
    for i in range(LOOKBACK + 1, len(df)):
        rh = rolling_high[i]
        if np.isnan(rh):
            continue

        price = closes[i]
        prev  = closes[i - 1]

        # Primera vez que cierra sobre el máximo: hoy sí, ayer no
        if price > rh and prev <= rolling_high[i - 1]:
            signals.append({
                "ticker":     ticker,
                "action":     "buy",
                "price":      float(price),
                "roll_high":  float(rh),
                "score":      float((price - rh) / rh),
                "label":      f"Breakout 50d — cierre ${price:.2f} > max ${rh:.2f}",
                "bar_idx":    i,
            })
            break

    return signals


def check_exit(
    position: dict,
    current_price: float,
    trading_days_held: int,
) -> tuple[bool, str]:
    entry = position["entry_price"]
    peak  = position.get("peak_price", entry)
    pnl   = (current_price - entry) / entry
    fp    = (current_price - peak) / peak if peak > 0 else 0.0

    if pnl <= EXIT["stop_loss"]:
        return True, f"Stop loss: {pnl:.1%}"
    if pnl >= EXIT["hard_target"]:
        return True, f"Target +{pnl:.1%} alcanzado"
    if pnl >= EXIT["trailing_trigger"] and fp <= -EXIT["trailing_pct"]:
        return True, f"Trailing stop: {pnl:.1%} final"
    if trading_days_held >= EXIT["time_stop_days"]:
        return True, f"Stop de tiempo: {trading_days_held}d — {pnl:+.1%}"
    return False, ""
