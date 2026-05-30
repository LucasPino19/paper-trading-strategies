"""
ICT Order Blocks + VWAP + EMA(20) — adaptado de estrategias.py para paper trading en stocks.
Entra cuando el precio toca un Order Block con alineación de VWAP y tendencia EMA.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

# ── Parámetros ────────────────────────────────────────────────────────────────
ICT_IMPULSO   = 3     # velas alcistas/bajistas consecutivas para confirmar OB
ICT_MAX_EDAD  = 200   # índices hacia atrás en que un OB sigue activo
EMA_PERIOD    = 20    # EMA de cierres diarios para filtro de tendencia
OB_STOP_MULT  = 1.5   # stop loss = tamaño OB × este factor
OB_TARGET_MULT = 3.0  # take profit = tamaño OB × este factor

EXIT = {
    "stop_loss":       -0.07,   # -7%
    "hard_target":      0.20,   # +20%
    "trailing_trigger": 0.10,   # trailing activa a +10%
    "trailing_pct":     0.05,   # trail 5% desde pico
    "time_stop_days":   7,      # máx 7 días (OBs son señales de corto plazo)
}


# ── Indicadores ───────────────────────────────────────────────────────────────

def calcular_vwap(df: pd.DataFrame) -> np.ndarray:
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    df = df.copy()
    df["_tp"]   = tp
    df["_tpv"]  = tp * df["Volume"]
    df["_date"] = df.index.normalize()
    df["_ctpv"] = df.groupby("_date")["_tpv"].cumsum()
    df["_cvol"] = df.groupby("_date")["Volume"].cumsum()
    return (df["_ctpv"] / df["_cvol"].replace(0, float("nan"))).ffill().values


def calcular_ema_tendencia(df: pd.DataFrame, period: int = EMA_PERIOD) -> str | None:
    """Devuelve 'LONG', 'SHORT' o None si no hay suficientes datos."""
    df_d = df["Close"].resample("D").last().dropna()
    if len(df_d) < period + 2:
        return None
    closes = df_d.values
    k = 2 / (period + 1)
    ema = np.zeros(len(closes))
    ema[0] = closes[0]
    for i in range(1, len(closes)):
        ema[i] = closes[i] * k + ema[i - 1] * (1 - k)
    # Usar la EMA de ayer (penúltimo) contra el cierre de ayer
    return "LONG" if closes[-2] > ema[-2] else "SHORT"


# ── Detección de Order Blocks (tomada de estrategias.py) ─────────────────────

def detectar_obs(df: pd.DataFrame, impulso: int = ICT_IMPULSO) -> tuple[list[dict], list[dict]]:
    opens  = df["Open"].values
    closes = df["Close"].values
    highs  = df["High"].values
    lows   = df["Low"].values
    ob_bull, ob_bear = [], []

    for i in range(1, len(df) - impulso - 1):
        # OB alcista: vela bajista seguida de N velas alcistas con momentum
        alc = sum(
            1 for k in range(i + 1, min(i + 1 + impulso, len(df)))
            if closes[k] > opens[k] and closes[k] > closes[k - 1]
        )
        if closes[i] < opens[i] and alc >= impulso:
            ob_bull.append({
                "indice":   i,
                "ob_high":  float(max(opens[i], closes[i])),
                "ob_low":   float(lows[i]),
                "ob_fecha": str(df.index[i]),
            })
        # OB bajista: vela alcista seguida de N velas bajistas
        baj = sum(
            1 for k in range(i + 1, min(i + 1 + impulso, len(df)))
            if closes[k] < opens[k] and closes[k] < closes[k - 1]
        )
        if closes[i] > opens[i] and baj >= impulso:
            ob_bear.append({
                "indice":   i,
                "ob_high":  float(highs[i]),
                "ob_low":   float(min(opens[i], closes[i])),
                "ob_fecha": str(df.index[i]),
            })
    return ob_bull, ob_bear


# ── Señales ───────────────────────────────────────────────────────────────────

def scan_signals(ticker: str, df: pd.DataFrame) -> list[dict]:
    """
    Devuelve señales ICT para el ticker dado.
    Busca OBs activos donde la última vela toca la zona con VWAP + EMA alineados.
    """
    if len(df) < EMA_PERIOD * 2 + 10:
        return []

    vwap      = calcular_vwap(df)
    tendencia = calcular_ema_tendencia(df)
    ob_bull, ob_bear = detectar_obs(df)

    closes = df["Close"].values
    highs  = df["High"].values
    lows   = df["Low"].values
    j      = len(df) - 1
    precio = closes[j]
    vwap_j = vwap[j]
    min_idx = max(0, j - ICT_MAX_EDAD)

    signals = []

    for ob_list, tipo in [(ob_bull, "bull"), (ob_bear, "bear")]:
        # Filtrar OBs contra la tendencia
        if tendencia == "LONG" and tipo == "bear":
            continue
        if tendencia == "SHORT" and tipo == "bull":
            continue

        for ob in ob_list:
            idx     = ob["indice"]
            ob_high = ob["ob_high"]
            ob_low  = ob["ob_low"]
            ob_size = ob_high - ob_low
            if idx < min_idx or idx >= j - 3 or ob_size <= 0:
                continue

            toca = lows[j] <= ob_high and highs[j] >= ob_low

            if tipo == "bull" and toca and precio > vwap_j:
                signals.append({
                    "ticker":   ticker,
                    "action":   "buy",
                    "ob_tipo":  tipo,
                    "entry":    ob_high,
                    "stop":     ob_low  - ob_size * OB_STOP_MULT,
                    "target":   ob_high + ob_size * OB_TARGET_MULT,
                    "ob_size":  ob_size,
                    "price":    float(precio),
                    "tendencia": tendencia or "neutral",
                    "score":    ob_size / precio,
                    "label":    f"ICT OB bull | EMA {tendencia} | VWAP ✓",
                })
            elif tipo == "bear" and toca and precio < vwap_j:
                signals.append({
                    "ticker":   ticker,
                    "action":   "sell_short",
                    "ob_tipo":  tipo,
                    "entry":    ob_low,
                    "stop":     ob_high + ob_size * OB_STOP_MULT,
                    "target":   ob_low  - ob_size * OB_TARGET_MULT,
                    "ob_size":  ob_size,
                    "price":    float(precio),
                    "tendencia": tendencia or "neutral",
                    "score":    ob_size / precio,
                    "label":    f"ICT OB bear | EMA {tendencia} | VWAP ✓",
                })

    return sorted(signals, key=lambda x: x["score"], reverse=True)


# ── Exits ─────────────────────────────────────────────────────────────────────

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
