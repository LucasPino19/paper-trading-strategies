"""AlpacaTrader: misma interfaz que PaperTrader, ejecuta órdenes reales en Alpaca paper."""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime
from typing import Optional

INITIAL_CAPITAL = 10_000.0
POSITION_SIZE_PCT = 0.30
MAX_OPEN_POSITIONS = 3

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    from alpaca.data.historical import StockHistoricalDataClient
    from alpaca.data.requests import StockLatestTradeRequest
    _ALPACA_AVAILABLE = True
except ImportError:
    _ALPACA_AVAILABLE = False

# ── Singleton de cliente de datos (reutilizado entre llamadas) ────────────────

_data_client_instance: Optional[object] = None


def _data_client():
    global _data_client_instance
    if _data_client_instance is None and _ALPACA_AVAILABLE:
        api_key    = os.environ.get("ALPACA_API_KEY", "")
        secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
        if api_key and secret_key:
            try:
                _data_client_instance = StockHistoricalDataClient(api_key, secret_key)
            except Exception:
                pass
    return _data_client_instance


def get_alpaca_price(ticker: str) -> Optional[float]:
    """Precio en tiempo real via Alpaca Data API. Devuelve None si no disponible."""
    client = _data_client()
    if client is None:
        return None
    try:
        req   = StockLatestTradeRequest(symbol_or_symbols=ticker)
        trade = client.get_stock_latest_trade(req)
        price = float(trade[ticker].price)
        return price if price > 0 else None
    except Exception:
        return None


# ── AlpacaTrader ──────────────────────────────────────────────────────────────

class AlpacaTrader:
    def __init__(self, data_file: str, initial_capital: float = INITIAL_CAPITAL):
        self.data_file      = data_file
        self.initial_capital = initial_capital
        self._state         = self._load()

        api_key    = os.environ.get("ALPACA_API_KEY", "")
        secret_key = os.environ.get("ALPACA_SECRET_KEY", "")
        self._trading_ok = _ALPACA_AVAILABLE and bool(api_key) and bool(secret_key)

        if self._trading_ok:
            try:
                self._tc = TradingClient(api_key, secret_key, paper=True)
            except Exception as e:
                print(f"[alpaca] Error inicializando TradingClient: {e}")
                self._trading_ok = False

    # ── Persistencia ──────────────────────────────────────────────────────────

    def _load(self) -> dict:
        os.makedirs(os.path.dirname(self.data_file), exist_ok=True)
        if os.path.exists(self.data_file):
            with open(self.data_file) as f:
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

    # ── Market clock ──────────────────────────────────────────────────────────

    def _market_open(self) -> bool:
        if not self._trading_ok:
            return False
        try:
            return self._tc.get_clock().is_open
        except Exception:
            return False

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
        actual_price  = price
        actual_shares = invest / price

        if self._trading_ok and self._market_open():
            try:
                order = self._tc.submit_order(MarketOrderRequest(
                    symbol=ticker,
                    notional=round(invest, 2),
                    side=OrderSide.BUY,
                    time_in_force=TimeInForce.DAY,
                ))
                print(f"[alpaca] Orden enviada {order.id}")
                time.sleep(3)
                try:
                    pos = self._tc.get_open_position(ticker)
                    actual_price  = float(pos.avg_entry_price)
                    actual_shares = float(pos.qty)
                    print(f"[alpaca] Fill: {ticker} @ ${actual_price:.2f} × {actual_shares:.4f}")
                except Exception:
                    pass
            except Exception as e:
                print(f"[alpaca] Error enviando orden: {e} — usando precio actual")
        elif self._trading_ok:
            print(f"[alpaca] Mercado cerrado — posición registrada sin orden real")

        actual_invest = actual_shares * actual_price
        self._state["cash"] -= actual_invest

        position = {
            "ticker": ticker,
            "entry_price": actual_price,
            "shares": actual_shares,
            "entry_value": actual_invest,
            "current_price": actual_price,
            "peak_price": actual_price,
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
            f"[trader] ✅ ABRE  {ticker} @ ${actual_price:.2f} | "
            f"{actual_shares:.4f} acciones | ${actual_invest:,.0f} invertido"
        )
        return position

    def close_position(self, ticker: str, price: float, reason: str) -> dict | None:
        if ticker not in self.open_positions:
            return None

        pos          = self.open_positions.pop(ticker)
        actual_price = price

        if self._trading_ok and self._market_open():
            try:
                self._tc.close_position(ticker)
                print(f"[alpaca] Orden de cierre enviada: {ticker}")
                time.sleep(3)
                latest = get_alpaca_price(ticker)
                if latest:
                    actual_price = latest
            except Exception as e:
                print(f"[alpaca] Error cerrando posición: {e}")

        proceeds = pos["shares"] * actual_price
        pnl      = proceeds - pos["entry_value"]
        pnl_pct  = pnl / pos["entry_value"]
        self._state["cash"] += proceeds

        trade = {
            **pos,
            "exit_price":  actual_price,
            "exit_date":   datetime.now().isoformat(),
            "proceeds":    proceeds,
            "pnl":         pnl,
            "pnl_pct":     pnl_pct,
            "exit_reason": reason,
        }
        self._state["closed_trades"].append(trade)
        self._save()

        emoji = "🟢" if pnl >= 0 else "🔴"
        print(f"[trader] {emoji} CIERRA {ticker} @ ${actual_price:.2f} | P&L: ${pnl:+,.0f} ({pnl_pct:+.1%}) | {reason}")
        return trade

    def update_position(self, ticker: str, current_price: float) -> None:
        if ticker not in self.open_positions:
            return
        pos   = self.open_positions[ticker]
        today = date.today().isoformat()

        live = get_alpaca_price(ticker)
        if live:
            current_price = live

        pos["current_price"] = current_price
        if current_price > pos.get("peak_price", current_price):
            pos["peak_price"] = current_price
        if pos.get("last_update_date") != today:
            pos["trading_days_held"] = pos.get("trading_days_held", 0) + 1
            pos["last_update_date"]  = today

        self._save()

    def mark_volume_spiked(self, ticker: str) -> None:
        if ticker in self.open_positions:
            self.open_positions[ticker]["volume_spiked"] = True
            self._save()

    def record_equity(self) -> float:
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

    def get_summary(self) -> dict:
        market_value = sum(
            p["shares"] * p.get("current_price", p["entry_price"])
            for p in self.open_positions.values()
        )
        invested   = sum(p["entry_value"] for p in self.open_positions.values())
        closed     = self._state["closed_trades"]
        realized   = sum(t["pnl"] for t in closed)
        wins       = sum(1 for t in closed if t["pnl"] > 0)
        total_equity = self._state["cash"] + market_value

        return {
            "initial_capital":  self.initial_capital,
            "cash":             self._state["cash"],
            "total_equity":     total_equity,
            "total_return_pct": (total_equity - self.initial_capital) / self.initial_capital,
            "realized_pnl":     realized,
            "unrealized_pnl":   market_value - invested,
            "open_positions":   len(self.open_positions),
            "closed_trades":    len(closed),
            "wins":             wins,
            "losses":           len(closed) - wins,
            "win_rate":         wins / len(closed) if closed else 0.0,
        }


# Alias para compatibilidad
PaperTrader = AlpacaTrader
