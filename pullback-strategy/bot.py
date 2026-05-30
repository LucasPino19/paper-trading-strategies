"""Bot Pullback EMA50 + ADX: entra en retrocesos a la EMA50 con tendencia confirmada por ADX."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

import yfinance as yf
import pandas as pd

from strategy import scan_signals, check_exit
from paper_trader import PaperTrader

# Pullback EMA50 + ADX necesita instrumentos con tendencias claras.
UNIVERSE = [
    "NVDA", "MSFT", "AAPL", "META", "AMZN",
    "GOOGL", "AVGO", "QQQ", "SPY", "XLK",
    "SOXX", "AMD", "TSM", "ASML", "V",
    "MA", "JPM", "UNH", "LLY", "ABBV",
]


def _calc_adx(df: pd.DataFrame, period: int = 14) -> float:
    """Calcula el ADX(period) sobre un DataFrame con columnas High, Low, Close."""
    high = df["High"]
    low = df["Low"]
    close = df["Close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr = tr.ewm(com=period - 1, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(com=period - 1, min_periods=period).mean() / atr.replace(0, float("nan"))
    minus_di = 100 * minus_dm.ewm(com=period - 1, min_periods=period).mean() / atr.replace(0, float("nan"))

    dx = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, float("nan")))
    adx = dx.ewm(com=period - 1, min_periods=period).mean()
    return float(adx.iloc[-1]) if not adx.empty else 0.0


def rankear_universe(tickers: list[str] = UNIVERSE, top_n: int = 10) -> list[str]:
    """Rankea por ADX(14). Usa 3mo para que ADX tenga suficiente historial (≥60 barras)."""
    print("[pull] Rankeando universo por ADX (tendencia)...")
    scores: dict[str, float] = {}
    for ticker in tickers:
        try:
            df = yf.download(ticker, period="3mo", interval="1d",
                             progress=False, auto_adjust=True)
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df.dropna(inplace=True)
            if len(df) < 28:   # mínimo para que ADX(14) converja
                continue
            adx_val = _calc_adx(df)
            if adx_val > 15:
                scores[ticker] = adx_val
        except Exception:
            continue
    ranked = sorted(scores, key=scores.get, reverse=True)[:top_n]
    if ranked:
        print(f"[rank] Top instrumentos: {', '.join(ranked[:3])}")
    return ranked


def descargar_datos(ticker: str) -> pd.DataFrame:
    try:
        # 1 año para que EMA200 y ADX tengan suficiente historial
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


def run_pullback_bot(trader: Optional[PaperTrader] = None) -> None:
    if trader is None:
        trader = PaperTrader()

    print(f"\n{'='*65}")
    print(f"  PULLBACK EMA50 + ADX BOT — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*65}")
    print(f"  Capital: ${trader.cash:,.0f} | Posiciones: {len(trader.open_positions)}/3")

    # ── Rankear universo y escanear candidatos ────────────────────────────
    if trader.can_open_position():
        candidates = rankear_universe()

        if not candidates:
            print("\n[pull] No hay instrumentos con ADX > 15 hoy.")
        else:
            print(f"\n[pull] Escaneando {len(candidates)} candidatos trending...")
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

            # Mayor ADX = tendencia más fuerte = entrada preferida
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
                    sps_score=sig["score"],
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
    run_pullback_bot()
