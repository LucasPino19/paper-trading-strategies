"""Bot BB Lower Bounce: compra rebotes en la banda inferior de Bollinger. Datos diarios."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import os
import yfinance as yf
import pandas as pd

from strategy import scan_signals, check_exit
from paper_trader import PaperTrader

# BB Lower Bounce funciona MEJOR con ETFs de índices y blue chips estables (siempre revierten a media).
UNIVERSE = [
    "SPY", "QQQ", "IWM", "DIA", "XLK",
    "XLF", "XLE", "XLV", "XLI", "XLU",
    "AAPL", "MSFT", "AMZN", "GOOGL", "META",
    "JPM", "JNJ", "PG", "KO", "WMT",
    "V", "HD", "UNH", "ABBV",
]


def _calc_rsi(series: pd.Series, period: int = 14) -> float:
    """Calcula el RSI(period) sobre una serie de precios. Devuelve el último valor."""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, min_periods=period).mean()
    avg_loss = loss.ewm(com=period - 1, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1]) if not rsi.empty else 50.0


def rankear_universe(tickers: list[str] = UNIVERSE, top_n: int = 10) -> list[str]:
    """Rankea por RSI(14) invertido — más oversold = mejor. Solo incluye RSI < 50."""
    print("[bb] Rankeando universo por RSI (más oversold = mejor candidato)...")
    scores: dict[str, float] = {}
    for ticker in tickers:
        try:
            df = yf.download(ticker, period="5d", interval="1d",
                             progress=False, auto_adjust=True)
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df.dropna(inplace=True)
            if len(df) < 15:
                # No hay suficiente historial en 5d para RSI; intentar con más datos
                df = yf.download(ticker, period="1mo", interval="1d",
                                 progress=False, auto_adjust=True)
                df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
                df.dropna(inplace=True)
            if len(df) < 15:
                continue
            rsi = _calc_rsi(df["Close"])
            if rsi < 50:
                scores[ticker] = -rsi  # más negativo = más oversold = mejor score
        except Exception:
            continue
    ranked = sorted(scores, key=scores.get, reverse=True)[:top_n]
    if ranked:
        print(f"[rank] Top instrumentos: {', '.join(ranked[:3])}")
    return ranked


def descargar_datos(ticker: str) -> pd.DataFrame:
    try:
        # 1 año para que EMA200 tenga suficiente historial
        df = yf.download(ticker, period="1y", interval="1d",
                         progress=False, auto_adjust=True)
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
        df.dropna(inplace=True)
        return df
    except Exception as e:
        print(f"  [data] error descargando {ticker}: {e}")
        return pd.DataFrame()


def get_current_price(ticker: str) -> Optional[float]:
    # Alpaca primero (tiempo real), yfinance como fallback
    from alpaca_trader import get_alpaca_price
    price = get_alpaca_price(ticker)
    if price:
        return price
    try:
        price = yf.Ticker(ticker).fast_info.last_price
        if price and float(price) > 0:
            return float(price)
    except Exception:
        pass
    return None


def run_bb_bounce_bot(trader: Optional[PaperTrader] = None) -> None:
    if trader is None:
        trader = PaperTrader()

    print(f"\n{'='*65}")
    print(f"  BB LOWER BOUNCE BOT — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*65}")
    print(f"  Capital: ${trader.cash:,.0f} | Posiciones: {len(trader.open_positions)}/3")

    # ── Rankear universo y escanear candidatos ────────────────────────────
    if trader.can_open_position():
        candidates = rankear_universe()

        if not candidates:
            print("\n[bb] No hay instrumentos con RSI < 50 hoy.")
        else:
            print(f"\n[bb] Escaneando {len(candidates)} candidatos oversold...")
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

            # El mejor score = RSI más bajo (oversold más pronunciado)
            all_signals.sort(key=lambda x: x["score"])

            for sig in all_signals:
                if not trader.can_open_position():
                    break
                price = get_current_price(sig["ticker"])
                if not price:
                    continue
                trader.open_position(
                    ticker=sig["ticker"],
                    price=price,
                    sps_score=sig["score"] * -1,
                    metrics={"short_float_pct": 0, "float_shares_m": 0, "dtc": 0},
                )

    # ── Actualizar y revisar salidas ──────────────────────────────────────
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
    run_bb_bounce_bot()
