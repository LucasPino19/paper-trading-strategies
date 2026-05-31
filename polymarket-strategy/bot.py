"""
Polymarket Momentum Bot — corre diariamente.

Estrategia: momentum de probabilidad en mercados de predicción.
  - Selecciona los 5 mercados más activos con momentum positivo de probabilidad.
  - Compra YES en cada mercado seleccionado (igual peso, 20% del capital).
  - Cierra si: take profit (+20pp), stop loss (-15pp) o sale del top.
"""
from __future__ import annotations

import sys
from datetime import datetime

from strategy import compute_momentum_signals
from portfolio import PolyPortfolio


def run() -> None:
    print(f"\n{'='*55}")
    print(f"  Polymarket Bot  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}\n")

    portfolio = PolyPortfolio()
    print(f"[bot] Equity actual: ${portfolio.total_equity():,.2f}")
    print(f"[bot] Posiciones abiertas: {len(portfolio.open_positions)}")

    # Obtener señales actuales del mercado
    selected, all_signals = compute_momentum_signals(top_n=5)

    if not selected and not portfolio.open_positions:
        print("[bot] Sin señales y sin posiciones. Sin cambios.")
        portfolio.save()
        sys.exit(0)

    # Actualizar precios y verificar exits
    portfolio.update_and_check_exits(all_signals)

    # Abrir nuevas posiciones si hay espacio
    n_open = len(portfolio.open_positions)
    if n_open < 5 and selected:
        print(f"\n[bot] Abriendo posiciones nuevas (tenemos {n_open}/5)...")
        portfolio.open_positions_from_signals(selected, max_pos=5, pos_size=0.20)

    portfolio.save()
    print(f"\n[bot] ✅ Finalizado. Equity: ${portfolio.total_equity():,.2f}")


if __name__ == "__main__":
    run()
