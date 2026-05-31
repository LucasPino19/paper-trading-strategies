"""Portfolio manager para Polymarket — mercados de predicción."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Optional

INITIAL_CAPITAL   = 10_000.0
_HERE             = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_FILE = os.path.join(_HERE, "data", "portfolio.json")

# Stop loss: salir si la probabilidad cae X puntos desde la entrada
STOP_LOSS_POINTS = 0.15   # -15 puntos de probabilidad
# Take profit: salir si la probabilidad sube Y puntos desde la entrada
TAKE_PROFIT_POINTS = 0.20  # +20 puntos de probabilidad


class PolyPortfolio:
    def __init__(self, data_file: str = DEFAULT_DATA_FILE):
        self.data_file = data_file
        self._state    = self._load()

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        if os.path.exists(self.data_file):
            with open(self.data_file) as f:
                return json.load(f)
        return {
            "initial_capital": INITIAL_CAPITAL,
            "cash"           : INITIAL_CAPITAL,
            "open_positions" : {},   # condition_id → position dict
            "closed_trades"  : [],
            "equity_history" : [{"date": date.today().isoformat(), "equity": INITIAL_CAPITAL}],
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

    def total_equity(self) -> float:
        # En mercados de predicción, el valor de una posición = shares * current_price
        # donde shares = número de contratos YES (cada uno vale $1 si resuelve)
        mkt = sum(
            p["shares"] * p.get("current_price", p["entry_price"])
            for p in self.open_positions.values()
        )
        return self._state["cash"] + mkt

    # ── Actualizar precios y verificar exits ──────────────────────────────────

    def update_and_check_exits(self, current_signals: list[dict]) -> None:
        """
        Actualiza precios de posiciones abiertas y cierra las que:
          - alcanzaron take profit (+20 puntos)
          - tocaron stop loss (-15 puntos)
          - ya no están en el top de mercados (momentum negativo)
        """
        today       = date.today().isoformat()
        price_map   = {s["condition_id"]: s["price"] for s in current_signals}
        active_ids  = {s["condition_id"] for s in current_signals if s["momentum"] > 0}
        to_close    = []

        for cond_id, pos in self.open_positions.items():
            current_price = price_map.get(cond_id, pos.get("current_price", pos["entry_price"]))
            pos["current_price"] = current_price
            pos["peak_price"]    = max(pos.get("peak_price", 0), current_price)

            if pos.get("last_update_date") != today:
                pos["trading_days_held"] = pos.get("trading_days_held", 0) + 1
                pos["last_update_date"]  = today

            entry = pos["entry_price"]
            move  = current_price - entry

            reason = None
            if move >= TAKE_PROFIT_POINTS:
                reason = f"Take profit (+{move:.3f})"
            elif move <= -STOP_LOSS_POINTS:
                reason = f"Stop loss ({move:.3f})"
            elif cond_id not in active_ids and len(self.open_positions) >= 5:
                reason = "Salió del top de momentum"

            if reason:
                to_close.append((cond_id, current_price, reason))

        for cond_id, price, reason in to_close:
            self._close_position(cond_id, price, reason)

        # Registrar equity del día
        today_eq = self.total_equity()
        history  = self._state["equity_history"]
        if history and history[-1]["date"] == today:
            history[-1]["equity"] = today_eq
        else:
            history.append({"date": today, "equity": today_eq})

        print(f"[portfolio] Equity actualizada: ${today_eq:,.2f}")

    def _close_position(self, cond_id: str, price: float, reason: str) -> None:
        pos = self.open_positions.pop(cond_id)
        pnl = pos["shares"] * (price - pos["entry_price"])
        self._state["cash"] += pos["shares"] * price
        self._state["closed_trades"].append({
            "ticker"           : pos["ticker"],
            "entry_price"      : pos["entry_price"],
            "exit_price"       : price,
            "shares"           : pos["shares"],
            "entry_value"      : pos["entry_value"],
            "pnl"              : pnl,
            "pnl_pct"         : (price - pos["entry_price"]) / pos["entry_price"] if pos["entry_price"] > 0 else 0,
            "entry_date"       : pos["entry_date"],
            "exit_date"        : datetime.now().isoformat(),
            "exit_reason"      : reason[:60],
            "trading_days_held": pos.get("trading_days_held", 0),
        })
        print(f"[close] {pos['ticker']}  p={price:.3f}  P&L: ${pnl:+,.2f}  ({reason})")

    # ── Abrir nuevas posiciones ───────────────────────────────────────────────

    def open_positions_from_signals(
        self,
        signals    : list[dict],
        max_pos    : int   = 5,
        pos_size   : float = 0.20,  # 20% del capital por posición
    ) -> None:
        """Abre posiciones en los top signals que no están ya en cartera."""
        today     = datetime.now().isoformat()
        today_d   = date.today().isoformat()
        existing  = set(self.open_positions.keys())
        n_open    = len(existing)

        for sig in signals:
            if n_open >= max_pos:
                break
            cond_id = sig["condition_id"]
            if cond_id in existing:
                continue

            price  = sig["price"]
            invest = min(
                self.total_equity() * pos_size,
                self._state["cash"]
            )
            if invest < 10 or price <= 0:
                continue

            # shares = número de contratos YES comprados
            shares = invest / price
            self._state["cash"] -= invest
            self.open_positions[cond_id] = {
                "ticker"           : sig["question"][:40],
                "outcome"          : sig["outcome"],
                "condition_id"     : cond_id,
                "entry_price"      : price,
                "shares"           : shares,
                "entry_value"      : invest,
                "current_price"    : price,
                "peak_price"       : price,
                "entry_date"       : today,
                "trading_days_held": 0,
                "last_update_date" : today_d,
                "momentum_entry"   : sig["momentum"],
            }
            existing.add(cond_id)
            n_open += 1
            print(f"[buy]  p={price:.3f}  ${invest:,.2f}  — {sig['question'][:55]}")
