"""Portfolio para Polymarket Soccer — Favorite-Longshot Bias."""
from __future__ import annotations

import json
import os
from datetime import date, datetime

INITIAL_CAPITAL   = 10_000.0
_HERE             = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_FILE = os.path.join(_HERE, "data", "portfolio.json")

TAKE_PROFIT = 0.12   # +12pp de subida → salir
STOP_LOSS   = 0.12   # -12pp de bajada → cortar
MAX_DAYS    = 10     # máximo días en posición


class SoccerPortfolio:
    def __init__(self, data_file: str = DEFAULT_DATA_FILE):
        self.data_file = data_file
        self._state    = self._load()

    def _load(self) -> dict:
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        if os.path.exists(self.data_file):
            with open(self.data_file) as f:
                return json.load(f)
        return {
            "initial_capital": INITIAL_CAPITAL,
            "cash"           : INITIAL_CAPITAL,
            "open_positions" : {},
            "closed_trades"  : [],
            "equity_history" : [{"date": date.today().isoformat(), "equity": INITIAL_CAPITAL}],
        }

    def save(self) -> None:
        with open(self.data_file, "w") as f:
            json.dump(self._state, f, indent=2)

    @property
    def cash(self) -> float:
        return self._state["cash"]

    @property
    def open_positions(self) -> dict:
        return self._state["open_positions"]

    def total_equity(self) -> float:
        mkt = sum(
            p["shares"] * p.get("current_price", p["entry_price"])
            for p in self.open_positions.values()
        )
        return self._state["cash"] + mkt

    def update_and_check_exits(self, fresh_signals: list[dict]) -> None:
        """Actualiza precios actuales y cierra posiciones que tocaron TP/SL/max días."""
        today     = date.today().isoformat()
        price_map = {s["condition_id"]: s["price"] for s in fresh_signals}
        to_close  = []

        for cond_id, pos in self.open_positions.items():
            current = price_map.get(cond_id, pos.get("current_price", pos["entry_price"]))
            pos["current_price"] = current
            pos["peak_price"]    = max(pos.get("peak_price", 0), current)

            if pos.get("last_update_date") != today:
                pos["trading_days_held"] = pos.get("trading_days_held", 0) + 1
                pos["last_update_date"]  = today

            move   = current - pos["entry_price"]
            days   = pos.get("trading_days_held", 0)
            reason = None

            if move >= TAKE_PROFIT:
                reason = f"Take profit (+{move:.3f})"
            elif move <= -STOP_LOSS:
                reason = f"Stop loss ({move:.3f})"
            elif days >= MAX_DAYS:
                reason = f"Max hold ({days}d)"

            if reason:
                to_close.append((cond_id, current, reason))

        for cond_id, price, reason in to_close:
            self._close(cond_id, price, reason)

        today_eq = self.total_equity()
        history  = self._state["equity_history"]
        if history and history[-1]["date"] == today:
            history[-1]["equity"] = today_eq
        else:
            history.append({"date": today, "equity": today_eq})

        print(f"[portfolio] Equity: ${today_eq:,.2f}")

    def _close(self, cond_id: str, price: float, reason: str) -> None:
        pos  = self.open_positions.pop(cond_id)
        pnl  = pos["shares"] * (price - pos["entry_price"])
        self._state["cash"] += pos["shares"] * price
        self._state["closed_trades"].append({
            "ticker"           : pos["ticker"][:50],
            "entry_price"      : pos["entry_price"],
            "exit_price"       : price,
            "shares"           : pos["shares"],
            "entry_value"      : pos["entry_value"],
            "pnl"              : pnl,
            "pnl_pct"         : (price - pos["entry_price"]) / pos["entry_price"],
            "entry_date"       : pos["entry_date"],
            "exit_date"        : datetime.now().isoformat(),
            "exit_reason"      : reason[:60],
            "trading_days_held": pos.get("trading_days_held", 0),
        })
        print(f"[close] {pos['ticker'][:40]}  p={price:.3f}  P&L: ${pnl:+,.2f}  ({reason})")

    def open_positions_from_signals(
        self,
        signals  : list[dict],
        max_pos  : int   = 5,
        pos_size : float = 0.20,
    ) -> None:
        today    = datetime.now().isoformat()
        today_d  = date.today().isoformat()
        existing = set(self.open_positions.keys())
        n_open   = len(existing)

        for sig in signals:
            if n_open >= max_pos:
                break
            cond_id = sig["condition_id"]
            if cond_id in existing:
                continue

            price  = sig["price"]
            invest = min(self.total_equity() * pos_size, self._state["cash"])
            if invest < 10 or price <= 0:
                continue

            shares = invest / price
            self._state["cash"] -= invest
            label  = f"[{sig['direction']}] {sig['question'][:38]}"

            self.open_positions[cond_id] = {
                "ticker"           : label,
                "direction"        : sig["direction"],
                "condition_id"     : cond_id,
                "entry_price"      : price,
                "shares"           : shares,
                "entry_value"      : invest,
                "current_price"    : price,
                "peak_price"       : price,
                "entry_date"       : today,
                "trading_days_held": 0,
                "last_update_date" : today_d,
            }
            existing.add(cond_id)
            n_open += 1
            print(f"[buy]  {sig['direction']} @ {price:.3f}  ${invest:,.2f}  — {sig['question'][:55]}")
