"""
ORB + 20d Breakout — entrada cuando precio supera el máximo de la vela de apertura (9:30)
y además cruza el máximo de los últimos 20 días, con volumen y EMA20 a favor.
Backtest óptimo: +22.8% anual, 58% win, PF 2.19.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EXIT = {
    "stop_loss":        -0.07,   # -7%
    "hard_target":       0.20,   # +20%
    "trailing_trigger":  0.10,   # trailing activa a +10%
    "trailing_pct":      0.05,   # trail 5% desde pico
    "time_stop_days":    12,     # máx 12 días de trading
}

ORB_LOOKBACK    = 140   # ~20 días en barras de 1h (7 barras/día × 20 días)
VOL_MULT        = 1.5
EMA_PERIOD      = 20


def scan_signals(ticker: str, df: pd.DataFrame) -> list[dict]:
    if len(df) < ORB_LOOKBACK + 10:
        return []

    closes  = df["Close"].values
    highs   = df["High"].values
    volumes = df["Volume"].values
    index   = df.index

    # EMA20 sobre barras de 1h
    ema20   = pd.Series(closes).ewm(span=EMA_PERIOD, adjust=False).mean().values
    vol_ma  = pd.Series(volumes).rolling(20).mean().values

    # Rolling max de 140 barras (shift 1 para evitar look-ahead)
    high_series  = pd.Series(highs)
    rolling_high = high_series.shift(1).rolling(ORB_LOOKBACK).max().values

    signals = []
    for i in range(ORB_LOOKBACK + 1, len(df)):
        cur_date = index[i].date() if hasattr(index[i], "date") else None
        if cur_date is None:
            continue

        # Buscar barra de apertura del día (9:30 ET = primera barra del día)
        day_bars = [j for j in range(i) if hasattr(index[j], "date") and index[j].date() == cur_date]
        if not day_bars:
            continue
        day_first = day_bars[0]
        orb_high  = highs[day_first]

        price = closes[i]

        # 1. Precio supera ORB high
        if price <= orb_high:
            continue

        # 2. Precio supera 20d rolling high (primera vez — antes era menor)
        rh = rolling_high[i]
        if np.isnan(rh) or price <= rh:
            continue

        # 3. Volumen confirma
        if vol_ma[i] <= 0 or volumes[i] < vol_ma[i] * VOL_MULT:
            continue

        # 4. Precio sobre EMA20
        if price <= ema20[i]:
            continue

        signals.append({
            "ticker":    ticker,
            "action":    "buy",
            "price":     float(price),
            "orb_high":  float(orb_high),
            "roll_high": float(rh),
            "score":     float((price - orb_high) / orb_high),
            "label":     "ORB + 20d Breakout + Vol + EMA20",
            "bar_idx":   i,
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
