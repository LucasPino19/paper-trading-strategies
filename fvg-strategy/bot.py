"""
Bot diario FVG: elige los activos con mayor volumen relativo del día y busca confluencia FVG+VWAP+Breakout.
Lógica fiel al fvg_bot.py original: primero rankear por volumen, luego analizar.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import yfinance as yf
import pandas as pd

from strategy import scan_signals, check_exit
from paper_trader import PaperTrader

UNIVERSE = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "GOOGL", "TSLA", "JPM", "V", "XOM",
    "UNH", "JNJ", "PG", "MA", "HD",
    "BAC", "ABBV", "CVX", "MRK", "PEP",
    "QQQ", "SPY", "AMD", "AVGO",
]


def rankear_universe(tickers: list[str] = UNIVERSE, top_n: int = 10) -> list[str]:
    """Rankea por ratio volumen hoy / promedio 20d. Devuelve top_n tickers."""
    print("[fvg] Rankeando universo por volumen relativo...")
    scores: dict[str, float] = {}
    for ticker in tickers:
        try:
            df = yf.download(ticker, period="5d", interval="1d",
                             progress=False, auto_adjust=True)
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df.dropna(inplace=True)
            if len(df) < 2:
                continue
            avg_vol = float(df["Volume"].iloc[:-1].mean())
            today_vol = float(df["Volume"].iloc[-1])
            if avg_vol > 0:
                scores[ticker] = today_vol / avg_vol
        except Exception:
            continue
    ranked = sorted(scores, key=scores.get, reverse=True)[:top_n]
    if ranked:
        print(f"[rank] Top instrumentos: {', '.join(ranked[:3])}")
    return ranked


def descargar_datos(ticker: str) -> pd.DataFrame:
    try:
        df = yf.download(ticker, period="3mo", interval="1h",
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


def run_fvg_bot(trader: Optional[PaperTrader] = None) -> None:
    if trader is None:
        trader = PaperTrader()

    print(f"\n{'='*65}")
    print(f"  FVG BOT — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*65}")
    print(f"  Capital: ${trader.cash:,.0f} | Posiciones: {len(trader.open_positions)}/3")

    # ── Rankear universo y escanear candidatos ────────────────────────────
    all_signals = []
    if trader.can_open_position():
        candidates = rankear_universe()

        for ticker in candidates:
            if ticker in trader.open_positions:
                continue
            df = descargar_datos(ticker)
            if df.empty:
                continue
            sigs = scan_signals(ticker, df)
            if sigs:
                print(f"\n[fvg] {ticker}: {len(sigs)} señal(es) — {sigs[0]['label']}")
                all_signals.extend(sigs)

        if not all_signals:
            print("\n[fvg] Sin confluencia FVG+VWAP+Breakout en los candidatos hoy.")

        all_signals.sort(key=lambda x: x["score"], reverse=True)

        # ── Abrir posición si hay señal ────────────────────────────────────
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
            break  # un trade por día, igual que el original

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
    run_fvg_bot()
