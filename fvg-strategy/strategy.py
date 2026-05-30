"""
FVG + VWAP + Breakout — lógica de señales adaptada de fvg_bot.py para paper trading.
Entra solo cuando las 3 confluencias coinciden sobre el activo de mayor volumen del día.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── Parámetros ────────────────────────────────────────────────────────────────
BREAKOUT_VENTANA   = 20    # velas para calcular el nivel de breakout
FVG_MAX_EDAD       = 120   # índices hacia atrás en que un FVG sigue "activo"
CONFLUENCIA_WINDOW = 5     # velas recientes para buscar breakout

EXIT = {
    "stop_loss":       -0.06,   # -6%
    "hard_target":      0.15,   # +15%
    "trailing_trigger": 0.07,   # trailing activa a +7%
    "trailing_pct":     0.04,   # trail 4% desde pico
    "time_stop_days":   10,     # máx 10 días de trading
}


# ── Detección de FVG (tomada de fvg_bot.py) ───────────────────────────────────

def detectar_fvg(df: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    highs  = df["High"].values
    lows   = df["Low"].values
    alcistas, bajistas = [], []
    for i in range(1, len(df) - 1):
        if highs[i - 1] < lows[i + 1]:
            alcistas.append({
                "indice": i, "fecha": df.index[i],
                "zona_baja": float(highs[i - 1]),
                "zona_alta": float(lows[i + 1]),
                "tipo": "alcista",
            })
        if lows[i - 1] > highs[i + 1]:
            bajistas.append({
                "indice": i, "fecha": df.index[i],
                "zona_baja": float(highs[i + 1]),
                "zona_alta": float(lows[i - 1]),
                "tipo": "bajista",
            })
    return alcistas, bajistas


def calcular_vwap(df: pd.DataFrame) -> np.ndarray:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    df = df.copy()
    df["_tp"]   = tp
    df["_tpv"]  = tp * df["Volume"]
    df["_date"] = df.index.normalize()
    df["_ctpv"] = df.groupby("_date")["_tpv"].cumsum()
    df["_cvol"] = df.groupby("_date")["Volume"].cumsum()
    return (df["_ctpv"] / df["_cvol"]).values


def calcular_breakout(df: pd.DataFrame, ventana: int = BREAKOUT_VENTANA) -> tuple[np.ndarray, np.ndarray]:
    closes = df["Close"].values
    highs  = df["High"].values
    lows   = df["Low"].values
    bo_al  = np.zeros(len(df), dtype=bool)
    bo_ba  = np.zeros(len(df), dtype=bool)
    for i in range(ventana, len(df)):
        if closes[i] > highs[i - ventana: i].max():
            bo_al[i] = True
        if closes[i] < lows[i - ventana: i].min():
            bo_ba[i] = True
    return bo_al, bo_ba


# ── Señales ───────────────────────────────────────────────────────────────────

def scan_signals(ticker: str, df: pd.DataFrame) -> list[dict]:
    """
    Devuelve señales de trading para el ticker dado.
    Busca FVGs activos donde la última vela tiene confluencia VWAP + Breakout.
    """
    if len(df) < BREAKOUT_VENTANA + 10:
        return []

    fvg_al, fvg_ba = detectar_fvg(df)
    vwap            = calcular_vwap(df)
    bo_al, bo_ba    = calcular_breakout(df)

    closes = df["Close"].values
    highs  = df["High"].values
    lows   = df["Low"].values
    j      = len(df) - 1  # índice de la última vela
    precio = closes[j]
    vwap_j = vwap[j]

    signals = []
    min_idx = max(0, j - FVG_MAX_EDAD)

    for fvg in fvg_al + fvg_ba:
        idx = fvg["indice"]
        if idx < min_idx or idx >= j - 2:
            continue

        zona_baja = fvg["zona_baja"]
        zona_alta = fvg["zona_alta"]
        tamanio   = zona_alta - zona_baja
        if tamanio <= 0:
            continue

        # ¿Precio toca la zona FVG?
        toca = lows[j] <= zona_alta and highs[j] >= zona_baja
        if not toca:
            continue

        # Confluencia VWAP + Breakout (últimas 5 velas)
        w = CONFLUENCIA_WINDOW
        bo_reciente_al = bo_al[max(0, j - w): j + 1].any()
        bo_reciente_ba = bo_ba[max(0, j - w): j + 1].any()

        if fvg["tipo"] == "alcista" and precio > vwap_j and bo_reciente_al:
            signals.append({
                "ticker":    ticker,
                "action":    "buy",
                "fvg_tipo":  "alcista",
                "entry":     float(zona_alta),
                "stop":      float(zona_alta - tamanio * 1.5),
                "target":    float(zona_alta + tamanio * 2.0),
                "fvg_size":  tamanio,
                "price":     float(precio),
                "score":     tamanio / precio,  # FVG relativo al precio
                "label":     f"FVG alcista + VWAP + Breakout",
            })
        elif fvg["tipo"] == "bajista" and precio < vwap_j and bo_reciente_ba:
            signals.append({
                "ticker":    ticker,
                "action":    "sell_short",
                "fvg_tipo":  "bajista",
                "entry":     float(zona_baja),
                "stop":      float(zona_baja + tamanio * 1.5),
                "target":    float(zona_baja - tamanio * 2.0),
                "fvg_size":  tamanio,
                "price":     float(precio),
                "score":     tamanio / precio,
                "label":     f"FVG bajista + VWAP + Breakout",
            })

    return sorted(signals, key=lambda x: x["score"], reverse=True)


# ── Exits ─────────────────────────────────────────────────────────────────────

def check_exit(
    position: dict,
    current_price: float,
    trading_days_held: int,
) -> tuple[bool, str]:
    entry  = position["entry_price"]
    peak   = position.get("peak_price", entry)
    pnl    = (current_price - entry) / entry
    fp     = (current_price - peak) / peak if peak > 0 else 0.0

    if pnl <= EXIT["stop_loss"]:
        return True, f"Stop loss: {pnl:.1%}"
    if pnl >= EXIT["hard_target"]:
        return True, f"Target +{pnl:.1%} alcanzado"
    if pnl >= EXIT["trailing_trigger"] and fp <= -EXIT["trailing_pct"]:
        return True, f"Trailing stop: {pnl:.1%} final"
    if trading_days_held >= EXIT["time_stop_days"]:
        return True, f"Stop de tiempo: {trading_days_held}d — {pnl:+.1%}"
    return False, ""
