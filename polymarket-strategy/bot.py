"""
Polymarket Fade Bot — corre diariamente.

Flujo:
  1. Carga precios YES guardados del run anterior (prev_prices).
  2. Obtiene mercados activos de la Gamma API (precio actual).
  3. Detecta mercados que se movieron >15pp desde ayer.
  4. Confirma con Google News RSS que el movimiento fue por noticias reales.
  5. Abre posiciones de fade (compra el lado opuesto al movimiento).
  6. Actualiza posiciones abiertas y cierra las que tocaron TP/SL/max días.
  7. Guarda los precios actuales como prev_prices para mañana.
"""
from __future__ import annotations

import sys
from datetime import datetime

from strategy import get_active_markets, parse_yes_price, detect_fade_signals
from portfolio import PolyPortfolio


def run() -> None:
    print(f"\n{'='*55}")
    print(f"  Polymarket Fade Bot  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}\n")

    portfolio = PolyPortfolio()
    print(f"[bot] Equity actual: ${portfolio.total_equity():,.2f}")
    print(f"[bot] Posiciones abiertas: {len(portfolio.open_positions)}")

    # Obtener mercados activos
    markets = get_active_markets(limit=100)
    if not markets:
        print("[bot] Sin mercados disponibles. Guardando estado.")
        portfolio.save()
        sys.exit(0)

    # Construir mapa de precios actuales (YES)
    current_yes_prices: dict[str, float] = {}
    for m in markets:
        cond_id = m.get("conditionId") or m.get("id", "")
        if not cond_id:
            continue
        p = parse_yes_price(m)
        if p is not None:
            current_yes_prices[cond_id] = p

    print(f"[bot] Precios actuales obtenidos para {len(current_yes_prices)} mercados")
    print(f"[bot] Precios previos disponibles: {len(portfolio.last_market_prices)}")

    # Actualizar posiciones abiertas con precios frescos
    if portfolio.open_positions:
        portfolio.update_positions(current_yes_prices)

    # Detectar señales de fade vs precios de ayer
    if portfolio.last_market_prices:
        signals, _ = detect_fade_signals(
            markets     = markets,
            prev_prices = portfolio.last_market_prices,
            top_n       = 5,
        )

        n_open = len(portfolio.open_positions)
        if signals and n_open < 5:
            print(f"\n[bot] Abriendo posiciones fade (tenemos {n_open}/5)...")
            portfolio.open_fade_positions(signals, max_pos=5, pos_size=0.20)
        elif not signals:
            print("[bot] Sin señales fade confirmadas hoy.")
    else:
        print("\n[bot] Primer run — guardando precios de referencia para mañana.")
        print("      Mañana el bot podrá detectar movimientos de hoy.")

    # Guardar precios actuales como referencia para el próximo run
    portfolio.update_last_prices(current_yes_prices)
    portfolio.save()

    print(f"\n[bot] ✅ Finalizado. Equity: ${portfolio.total_equity():,.2f}")


if __name__ == "__main__":
    run()
