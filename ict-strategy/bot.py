"""Bot diario ICT: escanea acciones, entra cuando hay confluencia OB+VWAP+EMA."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import yfinance as yf
import pandas as pd

from strategy import scan_signals, check_exit
from paper_trader import PaperTrader

WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "GOOGL", "TSLA", "JPM", "V", "XOM",
    "UNH", "JNJ", "PG", "MA", "HD",
    "BAC", "ABBV", "CVX", "MRK", "PEP",
]


def descargar_datos(ticker: str) -> pd.DataFrame:
    try:
        df = yf.download(ticker, period="60d", interval="1h",
                         progress=False, auto_adjust=True)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df.dropna(inplace=True)
        return df
    except Exception as e:
        print(f"  [data] error descargando {ticker}: {e}")
        return pd.DataFrame()


def get_current_price(ticker: str) -> Optional[float]:
    try:
        price = yf.Ticker(ticker).fast_info.last_price
        if price and float(price) > 0:
            return float(price)
    except Exception:
        pass
    return None


def run_ict_bot(trader: Optional[PaperTrader] = None) -> None:
    if trader is None:
        trader = PaperTrader()

    print(f"\n{'='*65}")
    print(f"  ICT BOT — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*65}")
    print(f"  Capital: ${trader.cash:,.0f} | Posiciones: {len(trader.open_positions)}/3")

    # ── Scan de señales ────────────────────────────────────────────────────
    all_signals = []
    if trader.can_open_position():
        print(f"\n[ict] Escaneando {len(WATCHLIST)} activos...")
        for ticker in WATCHLIST:
            df = descargar_datos(ticker)
            if df.empty:
                continue
            sigs = scan_signals(ticker, df)
            if sigs:
                print(f"  {ticker}: {len(sigs)} señal(es) — {sigs[0]['label']}")
            all_signals.extend(sigs)

        all_signals.sort(key=lambda x: x["score"], reverse=True)

        # ── Abrir posiciones ───────────────────────────────────────────────
        for sig in all_signals:
            if not trader.can_open_position():
                break
            if sig["ticker"] in trader.open_positions:
                continue
            price = get_current_price(sig["ticker"])
            if not price:
                continue
            trader.open_position(
                ticker=sig["ticker"],
                price=price,
                sps_score=sig["score"] * 1000,
                metrics={"short_float_pct": 0, "float_shares_m": 0, "dtc": 0},
            )

        if not all_signals:
            print("[ict] Sin OBs tocados hoy.")

    # ── Actualizar posiciones abiertas ────────────────────────────────────
    to_close = []
    for ticker, pos in list(trader.open_positions.items()):
        price = get_current_price(ticker)
        if not price:
            continue
        trader.update_position(ticker, price)
        pos = trader.open_positions[ticker]
        should_close, reason = check_exit(
            position=pos,
            current_price=price,
            trading_days_held=pos.get("trading_days_held", 0),
        )
        pnl = (price - pos["entry_price"]) / pos["entry_price"]
        action = f"→ CIERRA: {reason}" if should_close else "Hold"
        print(f"  {ticker:5} ${price:.2f} ({pnl:+.1%}) | {pos.get('trading_days_held',0)}d | {action}")
        if should_close:
            to_close.append((ticker, price, reason))

    for ticker, price, reason in to_close:
        trader.close_position(ticker, price, reason)

    equity = trader.record_equity()
    s = trader.get_summary()
    print(f"\n  Equity: ${equity:,.0f} | Return: {s['total_return_pct']:+.1%}")


if __name__ == "__main__":
    run_ict_bot()
