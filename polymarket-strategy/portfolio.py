"""Portfolio manager para Polymarket — fade de overreaction."""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Optional

INITIAL_CAPITAL    = 10_000.0
_HERE              = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DATA_FILE  = os.path.join(_HERE, "data", "portfolio.json")

# Exit rules para el fade
TAKE_PROFIT_POINTS = 0.10   # +10pp de reversión → salir con ganancia
STOP_LOSS_POINTS   = 0.10   # −10pp de continuación → cortar pérdida
MAX_HOLD_DAYS      = 14     # máximo días en posición (mercado no resuelto)


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
            # Precios YES de mercados del último run (para detectar movimientos)
            "last_market_prices": {},  # condition_id → precio YES de ayer
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
    def last_market_prices(self) -> dict[str, float]:
        return self._state.get("last_market_prices", {})

    def total_equity(self) -> float:
        mkt = sum(
            p["shares"] * p.get("current_price", p["entry_price"])
            for p in self.open_positions.values()
        )
        return self._state["cash"] + mkt

    # ── Actualizar precios previos ─────────────────────────────────────────────

    def update_last_prices(self, current_yes_prices: dict[str, float]) -> None:
        """Guarda los precios YES actuales para usarlos como referencia mañana."""
        self._state["last_market_prices"] = current_yes_prices
        print(f"[portfolio] Guardados {len(current_yes_prices)} precios para referencia de mañana")

    # ── Actualizar posiciones abiertas ────────────────────────────────────────

    def update_positions(self, current_yes_prices: dict[str, float]) -> None:
        """
        Actualiza current_price de cada posición y registra equity del día.
        El precio de una posición es:
          - Para YES: precio YES actual.
          - Para NO: 1 - precio YES actual.
        Cuando un mercado desaparece de la API activa (resolvió), se consulta
        su precio final y se cierra la posición.
        """
        from strategy import get_market_resolved_price

        today    = date.today().isoformat()
        to_close = []

        for cond_id, pos in self.open_positions.items():
            if cond_id not in current_yes_prices:
                # Mercado no está en la lista activa — puede haber resuelto
                if pos.get("last_update_date") != today:
                    pos["trading_days_held"]    = pos.get("trading_days_held", 0) + 1
                    pos["last_update_date"]      = today
                    pos["days_missing_from_api"] = pos.get("days_missing_from_api", 0) + 1

                if pos.get("days_missing_from_api", 0) >= 1:
                    resolved = get_market_resolved_price(cond_id)
                    if resolved is not None:
                        # Solo cerrar si el precio está claramente resuelto (< 2% o > 98%)
                        if resolved < 0.02:
                            final_yes = 0.0
                        elif resolved > 0.98:
                            final_yes = 1.0
                        else:
                            print(f"[portfolio] Mercado aún no resuelto: {pos['ticker'][:45]} → YES={resolved:.3f} (esperando)")
                            continue
                        current = final_yes if pos["direction"] == "YES" else (1.0 - final_yes)
                        pos["current_price"] = current
                        print(f"[portfolio] Mercado resuelto: {pos['ticker'][:45]} → YES={final_yes:.0f} → posición={current:.0f}")
                        to_close.append((cond_id, current, "Mercado resuelto"))
                continue

            yes_p = current_yes_prices[cond_id]
            current = yes_p if pos["direction"] == "YES" else (1.0 - yes_p)
            pos["current_price"]         = current
            pos["peak_price"]            = max(pos.get("peak_price", 0), current)
            pos["days_missing_from_api"] = 0  # volvió a la API activa

            if pos.get("last_update_date") != today:
                pos["trading_days_held"] = pos.get("trading_days_held", 0) + 1
                pos["last_update_date"]  = today

            # Verificar exits
            entry = pos["entry_price"]
            move  = current - entry
            days  = pos.get("trading_days_held", 0)
            reason = None

            if move >= TAKE_PROFIT_POINTS:
                reason = f"Take profit (+{move:.3f})"
            elif move <= -STOP_LOSS_POINTS:
                reason = f"Stop loss ({move:.3f})"
            elif days >= MAX_HOLD_DAYS:
                reason = f"Max hold ({days} días)"

            if reason:
                to_close.append((cond_id, current, reason))

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
        entry = pos["entry_price"]
        self._state["closed_trades"].append({
            "ticker"           : pos["ticker"][:50],
            "entry_price"      : entry,
            "exit_price"       : price,
            "shares"           : pos["shares"],
            "entry_value"      : pos["entry_value"],
            "pnl"              : pnl,
            "pnl_pct"         : (price - entry) / entry if entry > 0 else 0,
            "entry_date"       : pos["entry_date"],
            "exit_date"        : datetime.now().isoformat(),
            "exit_reason"      : reason[:60],
            "trading_days_held": pos.get("trading_days_held", 0),
        })
        print(f"[close] {pos['ticker'][:40]}  p={price:.3f}  P&L: ${pnl:+,.2f}  ({reason})")

    # ── Abrir posiciones de fade ───────────────────────────────────────────────

    def open_fade_positions(
        self,
        signals  : list[dict],
        max_pos  : int   = 5,
        pos_size : float = 0.20,  # 20% del equity por posición
    ) -> None:
        """
        Abre posiciones de fade sobre los signals confirmados.
        Cada signal tiene: condition_id, direction, price, question, move.
        """
        today   = datetime.now().isoformat()
        today_d = date.today().isoformat()
        existing = set(self.open_positions.keys())
        n_open   = len(existing)

        for sig in signals:
            if n_open >= max_pos:
                break
            cond_id = sig["condition_id"]
            if cond_id in existing:
                continue

            price  = sig["price"]
            invest = min(
                self._state["initial_capital"] * pos_size,
                self._state["cash"],
            )
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
                "move_at_entry"    : sig["move"],
            }
            existing.add(cond_id)
            n_open += 1
            print(f"[buy]  {sig['direction']} @ {price:.3f}  ${invest:,.2f}  — {sig['question'][:55]}")
            print(f"       (movimiento previo: {sig['move']:+.3f}, fadeamos)")
