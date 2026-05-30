"""
Pullback EMA50 + ADX — compra cuando el precio retrocede a tocar la EMA50
en una tendencia alcista (precio > EMA200), rebota, y el ADX > 20 confirma
que el mercado está en tendencia (no lateral).
Backtest: +21.5% anual, 50% win rate, PF 1.37, DD máx -33%.
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

EMA_FAST    = 50
EMA_TREND   = 200
MA_TOL      = 0.025   # tolerancia ±2.5% para "tocar" la EMA50
ADX_PERIOD  = 14
ADX_MIN     = 20


def _adx(df: pd.DataFrame, p: int = ADX_PERIOD) -> pd.Series:
    hi, lo, cl = df["High"], df["Low"], df["Close"]
    tr  = pd.concat([hi - lo, (hi - cl.shift()).abs(), (lo - cl.shift()).abs()], axis=1).max(axis=1)
    dmp = (hi - hi.shift()).clip(lower=0)
    dmn = (lo.shift() - lo).clip(lower=0)
    # +DM solo cuando es mayor que -DM y viceversa
    dmp_clean = dmp.where(dmp > dmn, 0.0)
    dmn_clean = dmn.where(dmn >= dmp, 0.0)
    atr = tr.ewm(span=p, adjust=False).mean()
    dip = 100 * dmp_clean.ewm(span=p, adjust=False).mean() / atr.replace(0, np.nan)
    din = 100 * dmn_clean.ewm(span=p, adjust=False).mean() / atr.replace(0, np.nan)
    dx  = 100 * (dip - din).abs() / (dip + din).replace(0, np.nan)
    return dx.ewm(span=p, adjust=False).mean()


def scan_signals(ticker: str, df: pd.DataFrame) -> list[dict]:
    if len(df) < EMA_TREND + ADX_PERIOD + 5:
        return []

    closes = df["Close"]
    ema50  = closes.ewm(span=EMA_FAST,  adjust=False).mean()
    ema200 = closes.ewm(span=EMA_TREND, adjust=False).mean()
    adx_s  = _adx(df)

    j = len(df) - 1
    if j < 1:
        return []

    price     = float(closes.iloc[j])
    price_prev= float(closes.iloc[j - 1])
    ema50_j   = float(ema50.iloc[j])
    ema50_prev= float(ema50.iloc[j - 1])
    ema200_j  = float(ema200.iloc[j])
    adx_j     = float(adx_s.iloc[j])

    # 1. Tendencia alcista
    if price <= ema200_j:
        return []

    # 2. Precio toca la EMA50 (dentro de ±2.5%)
    near_ema50 = abs(price / ema50_j - 1) < MA_TOL
    if not near_ema50:
        return []

    # 3. Ayer estaba en o por debajo de la EMA50 (confirmación de que el retroceso llegó)
    if price_prev > ema50_prev * (1 + MA_TOL):
        return []

    # 4. Rebote (hoy cierra por encima de ayer)
    if price <= price_prev:
        return []

    # 5. ADX > 20 (mercado en tendencia, no lateral)
    if adx_j <= ADX_MIN:
        return []

    dist_from_ma = (price - ema50_j) / ema50_j

    return [{
        "ticker":  ticker,
        "action":  "buy",
        "price":   price,
        "ema50":   ema50_j,
        "ema200":  ema200_j,
        "adx":     adx_j,
        "score":   adx_j,   # mayor ADX = tendencia más fuerte = señal preferida
        "label":   f"Pullback EMA50 | ADX {adx_j:.0f} | dist {dist_from_ma:+.1%}",
    }]


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
