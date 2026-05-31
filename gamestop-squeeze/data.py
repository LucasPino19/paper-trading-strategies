"""Market data: finviz screener para tickers + yfinance para métricas detalladas."""
from __future__ import annotations

from datetime import datetime, timedelta, date

import pandas as pd
import requests
import yfinance as yf

FINVIZ_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Lista de respaldo si finviz falla
FALLBACK_TICKERS = [
    "GRPN", "HTZ", "BYND", "SPWR", "NKLA", "WKHS", "EXPR",
    "PRTY", "BBIG", "SDC", "ATER", "CLOV", "WISH", "KOSS",
    "MVIS", "SNDL", "NAKD", "BBBY", "AMC", "GME",
]


def get_screener_tickers(min_short_pct: int = 20) -> list[str]:
    """Obtiene tickers de finviz filtrados por short interest elevado."""
    url = (
        "https://finviz.com/screener.ashx"
        f"?v=111&f=sh_short_o{min_short_pct},cap_small&o=-short"
    )
    try:
        resp = requests.get(url, headers=FINVIZ_HEADERS, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(resp.text, header=0)
        for table in tables:
            if "Ticker" in table.columns:
                tickers = table["Ticker"].dropna().tolist()
                clean = [
                    str(t).strip()
                    for t in tickers
                    if str(t).strip().isalpha() and len(str(t).strip()) <= 5
                ]
                if clean:
                    print(f"[data] finviz devolvió {len(clean)} tickers")
                    return clean
    except Exception as e:
        print(f"[data] finviz falló ({e}), usando lista de respaldo")
    return FALLBACK_TICKERS


def get_stock_metrics(ticker: str) -> dict | None:
    """Devuelve métricas clave: short interest, float, DTC, volumen, precio."""
    try:
        tk = yf.Ticker(ticker)
        info = tk.info

        price = info.get("currentPrice") or info.get("regularMarketPrice")
        short_float = info.get("shortPercentOfFloat")
        float_shares = info.get("floatShares")
        avg_volume = info.get("averageDailyVolume10Day") or info.get("averageVolume")
        current_volume = info.get("volume") or info.get("regularMarketVolume")
        market_cap = info.get("marketCap")
        short_ratio = info.get("shortRatio")  # DTC

        if not price or not short_float or not float_shares or not avg_volume:
            return None

        # yfinance devuelve shortPercentOfFloat como decimal (0.45 = 45%)
        short_float_pct = float(short_float) * 100 if float(short_float) <= 1 else float(short_float)

        avg_vol = int(avg_volume)
        cur_vol = int(current_volume) if current_volume else avg_vol
        vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0.0

        return {
            "ticker": ticker,
            "price": float(price),
            "short_float_pct": short_float_pct,
            "float_shares_m": float(float_shares) / 1_000_000,
            "avg_volume": avg_vol,
            "current_volume": cur_vol,
            "volume_ratio": vol_ratio,
            "market_cap_m": float(market_cap) / 1_000_000 if market_cap else 0.0,
            "dtc": float(short_ratio) if short_ratio else 0.0,
            "fetched_at": datetime.now().isoformat(),
        }
    except Exception as e:
        print(f"[data] no se pudo obtener métricas de {ticker}: {e}")
        return None


def get_current_price(ticker: str) -> float | None:
    """Precio actual del ticker. Alpaca primero, yfinance como fallback."""
    import os, sys
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    try:
        from alpaca_trader import get_alpaca_price
        price = get_alpaca_price(ticker)
        if price:
            return price
    except Exception:
        pass
    try:
        tk = yf.Ticker(ticker)
        price = tk.fast_info.last_price
        if price and float(price) > 0:
            return float(price)
    except Exception:
        pass
    try:
        hist = yf.Ticker(ticker).history(period="2d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None


def get_price_history(ticker: str, days: int = 60) -> pd.DataFrame:
    """Historial OHLCV del ticker para los últimos N días."""
    try:
        end = datetime.now()
        start = end - timedelta(days=days)
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=True)
        return df
    except Exception as e:
        print(f"[data] historial fallido para {ticker}: {e}")
        return pd.DataFrame()
