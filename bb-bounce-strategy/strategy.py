"""
BB Lower Bounce — compra cuando el precio toca la banda inferior de Bollinger
y rebota al día siguiente, con RSI < 45 y tendencia alcista (precio > EMA200).
Backtest: +15.4% anual, 62% win rate, PF 2.29, DD máx -12%.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EXIT = {
    "stop_loss":        -0.07,   # -7%
    "hard_target":       0.15,   # +15%
    "trailing_trigger":  0.08,   # trailing activa a +8%
    "trailing_pct":      0.04,   # trail 4% desde pico
    "time_stop_days":    15,     # máx 15 días de trading
}

BB_PERIOD  = 20
BB_STD     = 2
RSI_PERIOD = 14
RSI_MAX    = 45    # no entrar si RSI ya está muy alto (momentum bajista)
EMA_TREND  = 200


def _rsi(series: pd.Series) -> pd.Series:
    d = series.diff()
    g = d.clip(lower=0).ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    l = (-d.clip(upper=0)).ewm(alpha=1/RSI_PERIOD, min_periods=RSI_PERIOD, adjust=False).mean()
    return 100 - 100 / (1 + g / l.replace(0, np.nan))


def scan_signals(ticker: str, df: pd.DataFrame) -> list[dict]:
    if len(df) < EMA_TREND + BB_PERIOD + 5:
        return []

    closes = df["Close"]
    sma    = closes.rolling(BB_PERIOD).mean()
    std    = closes.rolling(BB_PERIOD).std()
    lower  = sma - BB_STD * std
    ema200 = closes.ewm(span=EMA_TREND, adjust=False).mean()
    rsi_s  = _rsi(closes)

    # Condiciones alineadas con la última barra
    j = len(df) - 1

    # 1. Ayer tocó o perforó la banda inferior
    if j < 1:
        return []
    touched_bb = float(closes.iloc[j - 1]) <= float(lower.iloc[j - 1])
    if not touched_bb:
        return []

    # 2. Hoy rebota (cierre > cierre de ayer)
    if float(closes.iloc[j]) <= float(closes.iloc[j - 1]):
        return []

    # 3. RSI < 45 (zona oversold sin estar en caída libre)
    if float(rsi_s.iloc[j]) >= RSI_MAX:
        return []

    # 4. Tendencia alcista (precio sobre EMA200)
    if float(closes.iloc[j]) <= float(ema200.iloc[j]):
        return []

    price = float(closes.iloc[j])
    bb_dev = (float(lower.iloc[j - 1]) - price) / price   # qué tan lejos está de la banda

    return [{
        "ticker": ticker,
        "action": "buy",
        "price":  price,
        "lower_bb": float(lower.iloc[j - 1]),
        "rsi":    float(rsi_s.iloc[j]),
        "ema200": float(ema200.iloc[j]),
        "score":  float(rsi_s.iloc[j - 1]) * -1,   # RSI más bajo = señal más fuerte
        "label":  f"BB Lower Bounce | RSI {rsi_s.iloc[j]:.0f}",
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
