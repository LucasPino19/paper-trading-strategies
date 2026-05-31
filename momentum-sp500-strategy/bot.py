"""
Momentum SP500 Bot — rebalanceo mensual.

Lógica sin lookahead bias:
  - La señal se calcula sobre datos hasta AYER (cierre del último mes completo).
  - La ejecución usa el precio de cierre de AYER como precio de entrada.
  - Si ya rebalanceamos este mes, solo actualiza precios para la equity curve.
"""
from __future__ import annotations

import sys
from datetime import datetime

import yfinance as yf

from strategy import get_sp500_tickers, compute_momentum_top
from portfolio import MomentumPortfolio


def get_current_prices(tickers: list[str]) -> dict[str, float]:
    """Descarga el último precio de cierre disponible para cada ticker."""
    if not tickers:
        return {}
    try:
        raw = yf.download(tickers, period="2d", auto_adjust=True, progress=False)
        closes = raw["Close"] if "Close" in raw else raw
        if hasattr(closes.columns, "levels"):
            pass
        result = {}
        for t in tickers:
            try:
                s = closes[t].dropna() if t in closes.columns else None
                if s is not None and len(s) > 0:
                    result[t] = float(s.iloc[-1])
            except Exception:
                pass
        return result
    except Exception as e:
        print(f"[bot] Error actualizando precios: {e}")
        return {}


def run() -> None:
    print(f"\n{'='*55}")
    print(f"  Momentum SP500 Bot  —  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*55}\n")

    portfolio = MomentumPortfolio()
    print(f"[bot] Equity actual: ${portfolio.total_equity():,.2f}")
    print(f"[bot] Posiciones abiertas: {len(portfolio.open_positions)}")
    print(f"[bot] Último rebalanceo: {portfolio.last_rebalance or 'nunca'}")

    # ── Actualizar precios de posiciones existentes ─────────────────────────
    if portfolio.open_positions:
        current_prices = get_current_prices(list(portfolio.open_positions.keys()))
        portfolio.update_prices(current_prices)

    # ── Rebalancear si corresponde ──────────────────────────────────────────
    if portfolio.needs_rebalance():
        print("\n[bot] Nuevo mes detectado — iniciando rebalanceo...")

        tickers = get_sp500_tickers()
        selected, prices = compute_momentum_top(tickers, top_pct=0.05, lookback=12, skip=1)

        if not selected:
            print("[bot] Sin señal válida. Guardando estado actual.")
            portfolio.save()
            sys.exit(0)

        portfolio.rebalance(selected, prices)
    else:
        print(f"\n[bot] Ya rebalanceamos en {portfolio.last_rebalance}. Solo actualizando precios.")

    portfolio.save()
    print(f"\n[bot] ✅ Finalizado. Equity: ${portfolio.total_equity():,.2f}")


if __name__ == "__main__":
    run()
