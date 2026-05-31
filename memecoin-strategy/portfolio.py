"""Portfolio manager para Memecoin Momentum — basket semanal de 5 memecoins."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Optional

INITIAL_CAPITAL   = 10_000.0
_HERE             = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_FILE = os.path.join(_HERE, "data", "portfolio.json")


class MemePortfolio:
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
            "initial_capital": INITIAL_CAPITAL,
            "cash"           : INITIAL_CAPITAL,
            "open_positions" : {},
            "closed_trades"  : [],
            "equity_history" : [{"date": date.today().isoformat(), "equity": INITIAL_CAPITAL}],
            "last_rebalance" : None,  # "YYYY-WW" semana ISO
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

    # ── Actualizar precios ────────────────────────────────────────────────────

    def update_prices(self, prices: dict[str, float]) -> None:
        today = date.today().isoformat()
        for coin_id, pos in self.open_positions.items():
            if coin_id in prices and prices[coin_id] > 0:
                pos["current_price"] = prices[coin_id]
                pos["peak_price"]    = max(pos.get("peak_price", 0), prices[coin_id])
            if pos.get("last_update_date") != today:
                pos["trading_days_held"] = pos.get("trading_days_held", 0) + 1
                pos["last_update_date"]  = today

        today_eq = self.total_equity()
        history  = self._state["equity_history"]
        if history and history[-1]["date"] == today:
            history[-1]["equity"] = today_eq
        else:
            history.append({"date": today, "equity": today_eq})

        print(f"[portfolio] Equity actualizada: ${today_eq:,.2f}")

    # ── Rebalanceo semanal ────────────────────────────────────────────────────

    def needs_rebalance(self) -> bool:
        now        = datetime.now()
        # Solo rebalancear los lunes
        if now.weekday() != 0:
            return False
        current_week = now.strftime("%Y-%W")
        return self.last_rebalance != current_week

    def rebalance(self, selected: list[dict], all_coins: list[dict]) -> None:
        """
        Rebalanceo semanal: entra en las 5 memecoins con mayor momentum 7d positivo.
        selected: lista de dicts con id, symbol, name, current_price, price_7d_pct
        """
        now          = datetime.now()
        current_week = now.strftime("%Y-%W")
        today        = now.isoformat()

        price_map = {c["id"]: c["current_price"] for c in selected}
        price_map.update({c["id"]: c["current_price"] for c in all_coins})

        current_ids = set(self.open_positions.keys())
        new_ids     = {c["id"] for c in selected if c["current_price"] > 0}

        to_sell = current_ids - new_ids
        to_buy  = new_ids - current_ids
        to_keep = current_ids & new_ids

        eq_before = self.total_equity()
        print(f"\n[rebalance] Equity pre: ${eq_before:,.2f}")
        print(f"[rebalance] Mantener: {len(to_keep)} | Vender: {len(to_sell)} | Comprar: {len(to_buy)}")

        # Cerrar posiciones que salieron del top
        for coin_id in to_sell:
            pos   = self.open_positions[coin_id]
            price = price_map.get(coin_id, pos.get("current_price", pos["entry_price"]))
            pnl   = pos["shares"] * (price - pos["entry_price"])
            self._state["cash"] += pos["shares"] * price
            self._state["closed_trades"].append({
                "ticker"           : pos.get("symbol", coin_id),
                "entry_price"      : pos["entry_price"],
                "exit_price"       : price,
                "shares"           : pos["shares"],
                "entry_value"      : pos["entry_value"],
                "pnl"              : pnl,
                "pnl_pct"         : (price - pos["entry_price"]) / pos["entry_price"],
                "entry_date"       : pos["entry_date"],
                "exit_date"        : today,
                "exit_reason"      : "Rebalanceo semanal — salió del top",
                "trading_days_held": pos.get("trading_days_held", 0),
            })
            del self.open_positions[coin_id]
            print(f"[sell] {pos.get('symbol', coin_id)} @ ${price:.6g}  P&L: ${pnl:+,.2f}")

        total_eq       = self.total_equity()
        n_total        = len(new_ids)
        if n_total == 0:
            self._state["last_rebalance"] = current_week
            return

        target_per_pos = total_eq / n_total

        # Ajustar posiciones que se mantienen
        for coin_id in to_keep:
            pos           = self.open_positions[coin_id]
            price         = price_map.get(coin_id, pos.get("current_price", pos["entry_price"]))
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
                pos["shares"]       += extra_shares
                self._state["cash"] -= diff

        # Abrir nuevas posiciones
        coin_info = {c["id"]: c for c in selected}
        for coin_id in to_buy:
            price = price_map.get(coin_id)
            if not price or price <= 0:
                continue
            invest = min(target_per_pos, self._state["cash"])
            if invest < 1:
                continue
            info   = coin_info.get(coin_id, {})
            shares = invest / price
            self._state["cash"] -= invest
            self.open_positions[coin_id] = {
                "ticker"           : info.get("symbol", coin_id),
                "name"             : info.get("name", coin_id),
                "entry_price"      : price,
                "shares"           : shares,
                "entry_value"      : invest,
                "current_price"    : price,
                "peak_price"       : price,
                "entry_date"       : today,
                "trading_days_held": 0,
                "last_update_date" : date.today().isoformat(),
                "momentum_7d"      : info.get("price_7d_pct", 0),
            }
            print(f"[buy]  {info.get('symbol', coin_id)} @ ${price:.6g}  ${invest:,.2f}")

        self._state["last_rebalance"] = current_week
        eq_after = self.total_equity()
        print(f"[rebalance] Equity post: ${eq_after:,.2f}")
        print(f"[rebalance] Posiciones activas: {len(self.open_positions)}")
