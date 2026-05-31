"""
Memecoin Momentum Bot — rebalanceo semanal (lunes).

Sin lookahead bias:
  - La señal usa el retorno de los últimos 7 días (dato ya cerrado).
  - El precio de entrada es el último precio disponible de CoinGecko.
  - Solo entra si hay momentum positivo real (>0% en 7d).
"""
from __future__ import annotations

import sys
from datetime import datetime

from strategy import compute_momentum_top
from portfolio import MemePortfolio


def run() -> None:
    print(f"\n{'='*55}")
    print(f"  Memecoin Momentum Bot  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}\n")

    portfolio = MemePortfolio()
    print(f"[bot] Equity actual: ${portfolio.total_equity():,.2f}")
    print(f"[bot] Posiciones abiertas: {len(portfolio.open_positions)}")
    print(f"[bot] Último rebalanceo: {portfolio.last_rebalance or 'nunca'}")

    # Obtener precios actuales de memecoins en cartera
    selected, all_coins = compute_momentum_top(top_n=5)

    # Actualizar precios de posiciones existentes
    if portfolio.open_positions:
        price_map = {c["id"]: c["current_price"] for c in all_coins}
        # También incluir precios de posiciones que quizás ya no están en top
        price_map_selected = {c["id"]: c["current_price"] for c in selected}
        price_map.update(price_map_selected)
        portfolio.update_prices(price_map)

    # Rebalancear si es lunes y no rebalanceamos esta semana
    if portfolio.needs_rebalance():
        print("\n[bot] Nueva semana detectada (lunes) — iniciando rebalanceo...")
        if not selected:
            print("[bot] Sin memecoins con momentum positivo. Sin cambios.")
            portfolio.save()
            sys.exit(0)
        portfolio.rebalance(selected, all_coins)
    else:
        now = datetime.now()
        if now.weekday() != 0:
            print(f"\n[bot] No es lunes (hoy: {now.strftime('%A')}). Solo actualizando precios.")
        else:
            print(f"\n[bot] Ya rebalanceamos esta semana ({portfolio.last_rebalance}). Solo precios.")

    portfolio.save()
    print(f"\n[bot] ✅ Finalizado. Equity: ${portfolio.total_equity():,.2f}")


if __name__ == "__main__":
    run()
