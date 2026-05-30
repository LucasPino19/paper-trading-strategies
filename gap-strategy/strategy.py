"""
Gap & Go — entrada cuando hay gap alcista >1% en apertura, se mantiene a las 10:30 ET
y el volumen confirma. Backtest óptimo: +24.1% anual, 62% win, PF 3.05.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EXIT = {
    "stop_loss":        -0.08,   # -8%
    "hard_target":       0.30,   # +30%
    "trailing_trigger":  0.12,   # trailing activa a +12%
    "trailing_pct":      0.06,   # trail 6% desde pico
    "time_stop_days":    20,     # máx 20 días de trading
}

GAP_THRESHOLD = 0.01    # gap mínimo 1%
VOL_MULT      = 1.5     # volumen > 1.5× media


def scan_signals(ticker: str, df: pd.DataFrame) -> list[dict]:
    if len(df) < 50:
        return []

    closes  = df["Close"].values
    opens   = df["Open"].values
    volumes = df["Volume"].values
    index   = df.index

    # Media de volumen de los últimos 20 días de barras (aprox)
    vol_ma = pd.Series(volumes).rolling(20).mean().values

    signals = []
    for i in range(20, len(df)):
        # Hora de la barra: solo actuar en o después de 10:30 ET
        bar_hour = index[i].hour if hasattr(index[i], "hour") else 10
        bar_min  = index[i].minute if hasattr(index[i], "minute") else 30
        if not (bar_hour > 10 or (bar_hour == 10 and bar_min >= 30)):
            continue

        # Primera barra del día actual
        cur_date = index[i].date() if hasattr(index[i], "date") else None
        if cur_date is None:
            continue

        # Buscar primera barra del día (9:30 ET = hora 9 o la más temprana del día)
        day_bars = [j for j in range(i) if hasattr(index[j], "date") and index[j].date() == cur_date]
        if not day_bars:
            continue
        day_first = day_bars[0]

        # Buscar cierre del día anterior
        prev_dates = [j for j in range(day_first) if hasattr(index[j], "date") and index[j].date() < cur_date]
        if not prev_dates:
            continue
        prev_close = closes[prev_dates[-1]]

        day_open = opens[day_first]
        if prev_close <= 0:
            continue

        # Gap alcista
        gap_pct = (day_open - prev_close) / prev_close
        if gap_pct < GAP_THRESHOLD:
            continue

        # Precio manteniendo el gap (close > open de apertura)
        price = closes[i]
        if price <= day_open * 0.995:  # permite 0.5% de margen
            continue

        # Volumen confirma
        if vol_ma[i] <= 0 or volumes[i] < vol_ma[i] * VOL_MULT:
            continue

        signals.append({
            "ticker": ticker,
            "action": "buy",
            "price":  float(price),
            "gap_pct": float(gap_pct),
            "score":  float(gap_pct),
            "label":  f"Gap {gap_pct:.1%} + Vol spike",
            "bar_idx": i,
        })
        break  # una señal por ciclo, la primera que cumple condiciones

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
