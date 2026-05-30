"""
Bot diario FVG: elige el activo con mayor volumen del día y busca confluencia FVG+VWAP+Breakout.
Lógica fiel al fvg_bot.py original: primero seleccionar activo por volumen, luego analizar.
"""
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


def seleccionar_activo_por_volumen(tickers: list[str] = WATCHLIST, periodo: str = "5d") -> str:
    """Devuelve el ticker con mayor volumen promedio de los últimos días (igual que el original)."""
    print("[fvg] Buscando activo con mayor volumen...")
    volumenes: dict[str, float] = {}
    for ticker in tickers:
        try:
            df = yf.download(ticker, period=periodo, interval="1d",
                             progress=False, auto_adjust=True)
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            if not df.empty:
                volumenes[ticker] = float(df["Volume"].mean())
        except Exception:
            continue
    if not volumenes:
        return "NVDA"
    mejor = max(volumenes, key=volumenes.get)
    print(f"  → Activo seleccionado: {mejor} (vol promedio: {volumenes[mejor]:,.0f})")
    return mejor


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

    # ── Selección de activo por volumen (fiel al original) ────────────────
    all_signals = []
    if trader.can_open_position():
        ticker = seleccionar_activo_por_volumen()

        # Si ya tenemos posición en ese activo, igual actualizamos pero no abrimos doble
        if ticker not in trader.open_positions:
            df = descargar_datos(ticker)
            if not df.empty:
                sigs = scan_signals(ticker, df)
                if sigs:
                    print(f"\n[fvg] {ticker}: {len(sigs)} señal(es) — {sigs[0]['label']}")
                    all_signals = sigs
                else:
                    print(f"\n[fvg] {ticker}: sin confluencia FVG+VWAP+Breakout hoy.")

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
