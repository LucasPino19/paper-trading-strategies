"""Lógica de entrada/salida y scoring SPS para la estrategia GameStop squeeze."""
from __future__ import annotations

# ── Condiciones de entrada ────────────────────────────────────────────────────
ENTRY = {
    "min_short_float_pct": 40.0,  # short interest > 40% del float
    "max_float_m": 100.0,          # float < 100M acciones
    "min_dtc": 5.0,                # días para cubrir > 5
    "min_volume_ratio": 2.0,       # volumen actual > 2x promedio
    "min_price": 1.0,              # evitar penny stocks sin datos
}

# ── Condiciones de salida ─────────────────────────────────────────────────────
EXIT = {
    # 1. Stop loss: si cae -15% desde entrada, cortar pérdida
    "stop_loss": -0.15,
    # 2. Target duro: +150% → tomar ganancia completa
    "hard_target": 1.50,
    # 3. Trailing stop: cuando sube >30%, no dejar caer más del 20% desde el pico
    "trailing_trigger": 0.30,
    "trailing_pct": 0.20,
    # 4. Stop de tiempo: si a los 20 días de trading no subió >10%, salir
    "time_stop_days": 20,
    "time_stop_min_gain": 0.10,
    # 5. Agotamiento del squeeze: si el volumen vuelve a la normalidad
    #    después de un spike Y la posición es rentable → cerrar
    "vol_spike_threshold": 3.0,   # volumen > 3x avg = spike confirmado
    "vol_exhaustion_ratio": 1.5,  # volumen < 1.5x avg = squeeze terminó
}

# ── Pesos del SPS (Squeeze Potential Score) ───────────────────────────────────
SPS_WEIGHTS = {
    "short_float": 0.35,
    "dtc": 0.25,
    "float_size": 0.20,
    "volume": 0.20,
}


# ── Funciones de scoring individuales ────────────────────────────────────────

def _score_short_float(pct: float) -> float:
    if pct < 20:  return 0
    if pct < 40:  return 25
    if pct < 70:  return 60
    if pct < 100: return 85
    return 100


def _score_dtc(dtc: float) -> float:
    if dtc < 3:  return 10
    if dtc < 7:  return 40
    if dtc < 15: return 75
    return 100


def _score_float(float_m: float) -> float:
    if float_m > 500: return 0
    if float_m > 100: return 20
    if float_m > 10:  return 65
    return 100


def _score_volume(vol_ratio: float) -> float:
    if vol_ratio < 1.5: return 0
    if vol_ratio < 2:   return 20
    if vol_ratio < 3:   return 50
    if vol_ratio < 5:   return 75
    return 100


def calculate_sps(metrics: dict) -> float:
    """Calcula el Squeeze Potential Score (0–100)."""
    score = (
        _score_short_float(metrics.get("short_float_pct", 0)) * SPS_WEIGHTS["short_float"]
        + _score_dtc(metrics.get("dtc", 0)) * SPS_WEIGHTS["dtc"]
        + _score_float(metrics.get("float_shares_m", 999)) * SPS_WEIGHTS["float_size"]
        + _score_volume(metrics.get("volume_ratio", 0)) * SPS_WEIGHTS["volume"]
    )
    return round(score, 1)


def should_enter(metrics: dict) -> tuple[bool, str]:
    """
    Evalúa si un ticker cumple las condiciones de entrada.
    Retorna (entrar: bool, razón: str).
    """
    short_pct = metrics.get("short_float_pct", 0)
    float_m   = metrics.get("float_shares_m", 999)
    dtc       = metrics.get("dtc", 0)
    vol_ratio = metrics.get("volume_ratio", 0)
    price     = metrics.get("price", 0)

    if price < ENTRY["min_price"]:
        return False, f"Precio ${price:.2f} < ${ENTRY['min_price']} mínimo (penny stock)"
    if short_pct < ENTRY["min_short_float_pct"]:
        return False, f"Short {short_pct:.1f}% < {ENTRY['min_short_float_pct']}% requerido"
    if float_m > ENTRY["max_float_m"]:
        return False, f"Float {float_m:.0f}M > {ENTRY['max_float_m']}M máximo"
    if dtc < ENTRY["min_dtc"]:
        return False, f"DTC {dtc:.1f}d < {ENTRY['min_dtc']}d requerido"
    if vol_ratio < ENTRY["min_volume_ratio"]:
        return False, f"Volumen {vol_ratio:.1f}x < {ENTRY['min_volume_ratio']}x requerido"

    sps = calculate_sps(metrics)
    return True, (
        f"SPS {sps:.0f}/100 | Short {short_pct:.0f}% | "
        f"Float {float_m:.0f}M | DTC {dtc:.1f}d | Vol {vol_ratio:.1f}x"
    )


def check_exit(
    position: dict,
    current_price: float,
    current_volume: int,
    avg_volume: int,
    trading_days_held: int,
) -> tuple[bool, str]:
    """
    Evalúa si una posición abierta debe cerrarse.
    Retorna (cerrar: bool, razón: str).

    Condiciones en orden de prioridad:
      1. Stop loss -15%
      2. Target duro +150%
      3. Trailing stop 20% desde pico (activa cuando +30%)
      4. Stop de tiempo (20 días sin >10%)
      5. Agotamiento del squeeze (vol vuelve a normal con ganancia)
    """
    entry_price = position["entry_price"]
    peak_price  = position.get("peak_price", entry_price)
    vol_spiked  = position.get("volume_spiked", False)

    pnl_pct      = (current_price - entry_price) / entry_price
    from_peak    = (current_price - peak_price) / peak_price if peak_price > 0 else 0
    vol_ratio    = current_volume / avg_volume if avg_volume > 0 else 0

    # 1. Stop loss
    if pnl_pct <= EXIT["stop_loss"]:
        return True, f"Stop loss: {pnl_pct:.1%} desde entrada"

    # 2. Target duro
    if pnl_pct >= EXIT["hard_target"]:
        return True, f"Target +{pnl_pct:.1%} alcanzado — tomando ganancias"

    # 3. Trailing stop (solo si ya subió lo suficiente)
    if pnl_pct >= EXIT["trailing_trigger"] and from_peak <= -EXIT["trailing_pct"]:
        return True, (
            f"Trailing stop: -{abs(from_peak):.1%} desde pico "
            f"${peak_price:.2f} — ganancia final {pnl_pct:.1%}"
        )

    # 4. Stop de tiempo
    if (trading_days_held >= EXIT["time_stop_days"]
            and pnl_pct < EXIT["time_stop_min_gain"]):
        return True, (
            f"Stop de tiempo: {trading_days_held} días y solo {pnl_pct:.1%} — "
            "tesis no se materializó"
        )

    # 5. Agotamiento del squeeze
    if (vol_spiked
            and vol_ratio < EXIT["vol_exhaustion_ratio"]
            and pnl_pct > 0):
        return True, (
            f"Squeeze agotado: volumen volvió a {vol_ratio:.1f}x tras spike — "
            f"tomando +{pnl_pct:.1%}"
        )

    return False, ""
