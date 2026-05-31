"""Portfolio manager para Momentum SP500 — basket mensual de ~22 posiciones."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Optional

INITIAL_CAPITAL   = 10_000.0
_HERE             = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_FILE = os.path.join(_HERE, "data", "portfolio.json")


class MomentumPortfolio:
    def __init__(self, data_file: str = DEFAULT_DATA_FILE):
        self.data_file = data_file
        self._state = self._load()

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        if os.path.exists(self.data_file):
            with open(self.data_file) as f:
                return json.load(f)
        return {
            "initial_capital" : INITIAL_CAPITAL,
            "cash"            : INITIAL_CAPITAL,
            "open_positions"  : {},   # ticker → position dict
            "closed_trades"   : [],
            "equity_history"  : [{"date": date.today().isoformat(), "equity": INITIAL_CAPITAL}],
            "last_rebalance"  : None, # "YYYY-MM" del último rebalance
        }

    def save(self) -> None:
        with open(self.data_file, "w") as f:
            json.dump(self._state, f, indent=2)

    # ── Propiedades ───────────────────────────────────────────────────────────

    @property
    def cash(self) -> float:
        return self._state["cash"]

    @property
    def open_positions(self) -> dict:
        return self._state["open_positions"]

    @property
    def last_rebalance(self) -> Optional[str]:
        return self._state.get("last_rebalance")

    def total_equity(self) -> float:
        mkt = sum(
            p["shares"] * p.get("current_price", p["entry_price"])
            for p in self.open_positions.values()
        )
        return self._state["cash"] + mkt

    # ── Precio de cada posición ───────────────────────────────────────────────

    def update_prices(self, prices: dict[str, float]) -> None:
        """Actualiza current_price y trading_days_held de cada posición."""
        today = date.today().isoformat()
        for ticker, pos in self.open_positions.items():
            if ticker in prices and prices[ticker] > 0:
                pos["current_price"] = prices[ticker]
                pos["peak_price"]    = max(pos.get("peak_price", 0), prices[ticker])
            if pos.get("last_update_date") != today:
                pos["trading_days_held"] = pos.get("trading_days_held", 0) + 1
                pos["last_update_date"]  = today

        # Registrar equity del día
        today_eq = self.total_equity()
        history  = self._state["equity_history"]
        if history and history[-1]["date"] == today:
            history[-1]["equity"] = today_eq
        else:
            history.append({"date": today, "equity": today_eq})

        print(f"[portfolio] Equity actualizada: ${today_eq:,.2f}")

    # ── Rebalanceo mensual ────────────────────────────────────────────────────

    def needs_rebalance(self) -> bool:
        current_month = datetime.now().strftime("%Y-%m")
        return self.last_rebalance != current_month

    def rebalance(self, selected_tickers: list[str], prices: dict[str, float]) -> None:
        """
        Ejecuta el rebalanceo mensual:
        1. Cierra posiciones que salieron del top
        2. Abre posiciones nuevas con peso igual al total de la cartera
        """
        current_month = datetime.now().strftime("%Y-%m")
        today         = datetime.now().isoformat()
        eq_before     = self.total_equity()

        current_tickers = set(self.open_positions.keys())
        new_tickers     = set(selected_tickers) & set(prices.keys())

        to_sell = current_tickers - new_tickers
        to_buy  = new_tickers - current_tickers
        to_keep = current_tickers & new_tickers

        print(f"\n[rebalance] Equity pre-rebalance: ${eq_before:,.2f}")
        print(f"[rebalance] Mantener: {len(to_keep)} | Vender: {len(to_sell)} | Comprar: {len(to_buy)}")

        # Cerrar posiciones que salieron del top
        for ticker in to_sell:
            pos   = self.open_positions[ticker]
            price = prices.get(ticker, pos.get("current_price", pos["entry_price"]))
            pnl   = pos["shares"] * (price - pos["entry_price"])
            self._state["cash"] += pos["shares"] * price
            self._state["closed_trades"].append({
                "ticker"           : ticker,
                "entry_price"      : pos["entry_price"],
                "exit_price"       : price,
                "shares"           : pos["shares"],
                "entry_value"      : pos["entry_value"],
                "pnl"              : pnl,
                "pnl_pct"         : (price - pos["entry_price"]) / pos["entry_price"],
                "entry_date"       : pos["entry_date"],
                "exit_date"        : today,
                "exit_reason"      : "Rebalanceo mensual — salió del top",
                "trading_days_held": pos.get("trading_days_held", 0),
            })
            del self.open_positions[ticker]
            print(f"[sell] {ticker} @ ${price:.2f}  P&L: ${pnl:+,.2f}")

        # Recalcular equity total disponible para distribuir
        total_eq   = self.total_equity()
        n_total    = len(new_tickers)  # posiciones finales totales
        if n_total == 0:
            print("[rebalance] Sin tickers válidos — sin cambios")
            self._state["last_rebalance"] = current_month
            return

        target_per_pos = total_eq / n_total

        # Ajustar posiciones existentes al nuevo peso target
        for ticker in to_keep:
            pos           = self.open_positions[ticker]
            price         = prices.get(ticker, pos.get("current_price", pos["entry_price"]))
            current_value = pos["shares"] * price
            diff          = target_per_pos - current_value
            if abs(diff) < 1:
                continue
            extra_shares = diff / price
            if diff > 0 and self._state["cash"] >= diff:
                pos["shares"]      += extra_shares
                pos["entry_value"] += diff
                self._state["cash"] -= diff
            elif diff < 0:
                pos["shares"]       += extra_shares   # negativo = vender
                self._state["cash"] -= diff            # negativo negativo = sumar cash

        # Comprar nuevas posiciones
        for ticker in to_buy:
            price = prices.get(ticker)
            if not price or price <= 0:
                continue
            invest = min(target_per_pos, self._state["cash"])
            if invest < 10:
                continue
            shares = invest / price
            self._state["cash"] -= invest
            self.open_positions[ticker] = {
                "ticker"           : ticker,
                "entry_price"      : price,
                "shares"           : shares,
                "entry_value"      : invest,
                "current_price"    : price,
                "peak_price"       : price,
                "entry_date"       : today,
                "trading_days_held": 0,
                "last_update_date" : date.today().isoformat(),
            }
            print(f"[buy]  {ticker} @ ${price:.2f}  ${invest:,.2f}")

        self._state["last_rebalance"] = current_month
        eq_after = self.total_equity()
        print(f"[rebalance] Equity post-rebalance: ${eq_after:,.2f}")
        print(f"[rebalance] Posiciones activas: {len(self.open_positions)}")
