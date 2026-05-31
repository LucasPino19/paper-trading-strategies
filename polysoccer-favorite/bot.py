"""Polymarket Soccer — Favorite-Longshot Bias Bot."""
from __future__ import annotations
import sys
from datetime import datetime
from strategy import find_favorite_signals
from portfolio import SoccerPortfolio


def run() -> None:
    print(f"\n{'='*55}")
    print(f"  Soccer Favorite Bot  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}\n")

    portfolio = SoccerPortfolio()
    print(f"[bot] Equity: ${portfolio.total_equity():,.2f}  |  Posiciones: {len(portfolio.open_positions)}")

    signals = find_favorite_signals(top_n=5)

    if portfolio.open_positions:
        portfolio.update_and_check_exits(signals)

    n_open = len(portfolio.open_positions)
    if signals and n_open < 5:
        print(f"\n[bot] Abriendo posiciones (tenemos {n_open}/5)...")
        portfolio.open_positions_from_signals(signals, max_pos=5, pos_size=0.20)
    elif not signals:
        print("[bot] Sin señales hoy.")

    portfolio.save()
    print(f"\n[bot] ✅ Finalizado. Equity: ${portfolio.total_equity():,.2f}")


if __name__ == "__main__":
    run()
