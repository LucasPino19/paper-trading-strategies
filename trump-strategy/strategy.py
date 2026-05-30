"""Lógica de entrada/salida para la estrategia Trump Sentiment."""
from __future__ import annotations

MIN_CONFIDENCE = 0.25  # confianza mínima para abrir posición

EXIT = {
    "stop_loss":       -0.08,  # -8%: Trump puede revertir rápido
    "hard_target":      0.50,  # +50%: tomar ganancia
    "trailing_trigger": 0.15,  # activar trailing a +15%
    "trailing_pct":     0.10,  # trail 10% desde pico
    "time_stop_days":   5,     # máx 5 días: las noticias de Trump duran poco
}


def should_enter(signal: dict) -> tuple[bool, str]:
    """Evalúa si una señal de buy de Trump justifica abrir posición."""
    if signal["action"] != "buy":
        return False, "Señal es de venta, no de compra"
    if signal["confidence"] < MIN_CONFIDENCE:
        return False, f"Confianza {signal['confidence']:.0%} < {MIN_CONFIDENCE:.0%} mínimo"
    return True, (
        f"Trump mencionó {signal['ticker']} positivamente "
        f"(confianza {signal['confidence']:.0%})"
    )


def check_exit(
    position: dict,
    current_price: float,
    trading_days_held: int,
    sell_signal: bool = False,
) -> tuple[bool, str]:
    """
    Evalúa si la posición debe cerrarse.

    Condiciones (en orden):
      0. Señal negativa de Trump → salida inmediata
      1. Stop loss -8%
      2. Target +50%
      3. Trailing stop (activa a +15%)
      4. Stop de tiempo 5 días
    """
    entry = position["entry_price"]
    peak  = position.get("peak_price", entry)
    pnl   = (current_price - entry) / entry
    fp    = (current_price - peak) / peak if peak > 0 else 0.0

    if sell_signal:
        return True, f"Trump dio señal negativa → cerrando a {pnl:+.1%}"
    if pnl <= EXIT["stop_loss"]:
        return True, f"Stop loss: {pnl:.1%}"
    if pnl >= EXIT["hard_target"]:
        return True, f"Target +{pnl:.1%} alcanzado"
    if pnl >= EXIT["trailing_trigger"] and fp <= -EXIT["trailing_pct"]:
        return True, f"Trailing stop: -{abs(fp):.1%} desde pico — ganancia final {pnl:.1%}"
    if trading_days_held >= EXIT["time_stop_days"]:
        return True, f"Stop de tiempo: {trading_days_held} días — {pnl:+.1%}"
    return False, ""
