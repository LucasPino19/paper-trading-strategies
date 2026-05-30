"""Portfolio de paper trading: posiciones, P&L y equity curve en JSON."""
from __future__ import annotations

import json
import os
from datetime import date, datetime

INITIAL_CAPITAL = 10_000.0
POSITION_SIZE_PCT = 0.30   # 30% del capital disponible por trade
MAX_OPEN_POSITIONS = 3

_HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_FILE = os.path.join(_HERE, "data", "portfolio.json")


class PaperTrader:
    def __init__(
        self,
        data_file: str = DEFAULT_DATA_FILE,
        initial_capital: float = INITIAL_CAPITAL,
    ):
        self.data_file = data_file
        self.initial_capital = initial_capital
        self._state = self._load()

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        if os.path.exists(self.data_file):
            with open(self.data_file, "r") as f:
                return json.load(f)
        return {
            "initial_capital": self.initial_capital,
            "cash": self.initial_capital,
            "open_positions": {},
            "closed_trades": [],
            "equity_history": [
                {"date": date.today().isoformat(), "equity": self.initial_capital}
            ],
        }

    def _save(self) -> None:
        with open(self.data_file, "w") as f:
            json.dump(self._state, f, indent=2)

    # ── Propiedades ───────────────────────────────────────────────────────────

    @property
    def cash(self) -> float:
        return self._state["cash"]

    @property
    def open_positions(self) -> dict:
        return self._state["open_positions"]

    def can_open_position(self) -> bool:
        return len(self.open_positions) < MAX_OPEN_POSITIONS

    # ── Operaciones ───────────────────────────────────────────────────────────

    def open_position(
        self, ticker: str, price: float, sps_score: float, metrics: dict
    ) -> dict | None:
        if ticker in self.open_positions:
            print(f"[trader] {ticker} ya está en el portfolio")
            return None
        if not self.can_open_position():
            print(f"[trader] máximo de posiciones ({MAX_OPEN_POSITIONS}) alcanzado")
            return None
        if price <= 0:
            return None

        invest = self._state["cash"] * POSITION_SIZE_PCT
        if invest > self._state["cash"]:
            print(f"[trader] capital insuficiente")
            return None

        shares = invest / price
        self._state["cash"] -= invest

        position = {
            "ticker": ticker,
            "entry_price": price,
            "shares": shares,
            "entry_value": invest,
            "current_price": price,
            "peak_price": price,
            "volume_spiked": False,
            "trading_days_held": 0,
            "last_update_date": None,
            "entry_date": datetime.now().isoformat(),
            "sps_score": sps_score,
            "short_float_pct": metrics.get("short_float_pct", 0),
            "float_shares_m": metrics.get("float_shares_m", 0),
            "dtc": metrics.get("dtc", 0),
        }
        self.open_positions[ticker] = position
        self._save()

        print(
            f"[trader] ✅ ABRE  {ticker} @ ${price:.2f} | "
            f"{shares:.0f} acciones | ${invest:,.0f} invertido | SPS {sps_score:.0f}"
        )
        return position

    def close_position(self, ticker: str, price: float, reason: str) -> dict | None:
        if ticker not in self.open_positions:
            return None

        pos = self.open_positions.pop(ticker)
        proceeds = pos["shares"] * price
        pnl = proceeds - pos["entry_value"]
        pnl_pct = pnl / pos["entry_value"]

        self._state["cash"] += proceeds

        trade = {
            **pos,
            "exit_price": price,
            "exit_date": datetime.now().isoformat(),
            "proceeds": proceeds,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "exit_reason": reason,
        }
        self._state["closed_trades"].append(trade)
        self._save()

        emoji = "🟢" if pnl >= 0 else "🔴"
        print(
            f"[trader] {emoji} CIERRA {ticker} @ ${price:.2f} | "
            f"P&L: ${pnl:+,.0f} ({pnl_pct:+.1%}) | {reason}"
        )
        return trade

    def update_position(self, ticker: str, current_price: float) -> None:
        """Actualiza precio actual, pico y contador de días (una vez por día)."""
        if ticker not in self.open_positions:
            return
        pos = self.open_positions[ticker]
        today = date.today().isoformat()

        pos["current_price"] = current_price
        if current_price > pos.get("peak_price", current_price):
            pos["peak_price"] = current_price
        # Solo incrementar trading_days una vez por día calendario
        if pos.get("last_update_date") != today:
            pos["trading_days_held"] = pos.get("trading_days_held", 0) + 1
            pos["last_update_date"] = today

        self._save()

    def mark_volume_spiked(self, ticker: str) -> None:
        if ticker in self.open_positions:
            self.open_positions[ticker]["volume_spiked"] = True
            self._save()

    def record_equity(self) -> float:
        """Calcula y guarda la equity total de hoy en el historial."""
        market_value = sum(
            p["shares"] * p.get("current_price", p["entry_price"])
            for p in self.open_positions.values()
        )
        total = self._state["cash"] + market_value

        today = date.today().isoformat()
        history = self._state["equity_history"]
        if history and history[-1]["date"] == today:
            history[-1]["equity"] = total
        else:
            history.append({"date": today, "equity": total})

        self._save()
        return total

    # ── Resumen ───────────────────────────────────────────────────────────────

    def get_summary(self) -> dict:
        market_value = sum(
            p["shares"] * p.get("current_price", p["entry_price"])
            for p in self.open_positions.values()
        )
        invested = sum(p["entry_value"] for p in self.open_positions.values())
        unrealized = market_value - invested

        closed = self._state["closed_trades"]
        realized = sum(t["pnl"] for t in closed)
        wins = sum(1 for t in closed if t["pnl"] > 0)
        losses = len(closed) - wins
        win_rate = wins / len(closed) if closed else 0.0

        total_equity = self._state["cash"] + market_value
        total_return = (total_equity - self.initial_capital) / self.initial_capital

        return {
            "initial_capital": self.initial_capital,
            "cash": self._state["cash"],
            "total_equity": total_equity,
            "total_return_pct": total_return,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "open_positions": len(self.open_positions),
            "closed_trades": len(closed),
            "wins": wins,
            "losses": losses,
            "win_rate": win_rate,
        }
