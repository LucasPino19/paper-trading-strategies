"""Bot Breakout 50d: detecta el primer cierre sobre el máximo de 50 días. Usa datos diarios."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import yfinance as yf
import pandas as pd

from strategy import scan_signals, check_exit
from paper_trader import PaperTrader

# Breakout 50d funciona mejor con instrumentos trending: ETFs, sector ETFs, commodity ETFs.
UNIVERSE = [
    "NVDA", "MSFT", "AAPL", "META", "AMZN",
    "GOOGL", "AVGO", "QQQ", "SPY", "XLK",
    "SOXX", "XLE", "XLF", "XLV", "IWM",
    "GLD", "SLV", "USO", "EEM", "AMD",
]


def rankear_universe(tickers: list[str] = UNIVERSE, top_n: int = 15) -> list[str]:
    """Rankea por momentum reciente: (close hoy - avg close 20d) / avg close 20d."""
    print("[b50d] Rankeando universo por momentum reciente...")
    scores: dict[str, float] = {}
    for ticker in tickers:
        try:
            df = yf.download(ticker, period="5d", interval="1d",
                             progress=False, auto_adjust=True)
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df.dropna(inplace=True)
            if len(df) < 2:
                continue
            avg_close = float(df["Close"].mean())
            today_close = float(df["Close"].iloc[-1])
            if avg_close > 0:
                scores[ticker] = (today_close - avg_close) / avg_close
        except Exception:
            continue
    ranked = sorted(scores, key=scores.get, reverse=True)[:top_n]
    if ranked:
        print(f"[rank] Top instrumentos: {', '.join(ranked[:3])}")
    return ranked


def descargar_datos(ticker: str) -> pd.DataFrame:
    try:
        df = yf.download(ticker, period="1y", interval="1d",
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


def run_breakout50d_bot(trader: Optional[PaperTrader] = None) -> None:
    if trader is None:
        trader = PaperTrader()

    print(f"\n{'='*65}")
    print(f"  BREAKOUT 50D BOT — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*65}")
    print(f"  Capital: ${trader.cash:,.0f} | Posiciones: {len(trader.open_positions)}/3")

    # ── Rankear universo y escanear candidatos ────────────────────────────
    if trader.can_open_position():
        candidates = rankear_universe()
        print(f"\n[b50d] Escaneando {len(candidates)} candidatos...")
        all_signals = []

        for ticker in candidates:
            if ticker in trader.open_positions:
                continue
            df = descargar_datos(ticker)
            if df.empty:
                continue
            sigs = scan_signals(ticker, df)
            if sigs:
                print(f"  {ticker}: {sigs[0]['label']}")
                all_signals.extend(sigs)

        all_signals.sort(key=lambda x: x["score"], reverse=True)

        for sig in all_signals:
            if not trader.can_open_position():
                break
            price = get_current_price(sig["ticker"])
            if not price:
                continue
            trader.open_position(
                ticker=sig["ticker"],
                price=price,
                sps_score=sig["score"] * 1000,
                metrics={"short_float_pct": 0, "float_shares_m": 0, "dtc": 0},
            )

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
    run_breakout50d_bot()
