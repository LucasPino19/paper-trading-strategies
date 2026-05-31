"""
Señal de momentum SP500 — sin lookahead bias.

Regla estricta:
  - Para decidir qué comprar HOY, solo se usa precio de AYER hacia atrás.
  - El momentum se calcula sobre cierre de hace 1 mes vs cierre de hace 13 meses.
  - Nunca se usa el precio del día actual para la señal de entrada.
"""
from __future__ import annotations

import time
import requests
from io import StringIO
from typing import Optional

import pandas as pd
import yfinance as yf


# ── Universo ──────────────────────────────────────────────────────────────────

def get_sp500_tickers() -> list[str]:
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        resp = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers=headers, timeout=15
        )
        resp.raise_for_status()
        df = pd.read_html(StringIO(resp.text))[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        print(f"[strategy] {len(tickers)} tickers del S&P 500 obtenidos")
        return tickers
    except Exception as e:
        print(f"[strategy] Error obteniendo tickers: {e}")
        # Fallback: top 100 más líquidas
        return [
            "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","AVGO","JPM",
            "LLY","V","UNH","XOM","MA","COST","HD","PG","JNJ","NFLX","ABBV","BAC",
            "KO","CRM","CVX","ORCL","MRK","AMD","WMT","PEP","TMO","ACN","ADBE","MCD",
            "CSCO","DHR","ABT","LIN","TXN","CAT","NKE","QCOM","PM","AMGN","INTC",
            "NEE","INTU","UPS","IBM","SPGI","BA","GS","HON","MS","RTX","LOW","BLK",
            "AMAT","PLD","AXP","ELV","SCHW","DE","MDLZ","VRTX","C","T","ADI","REGN",
            "GILD","SBUX","ISRG","CVS","ZTS","TMUS","MMC","CI","BDX","LRCX","SO",
            "MO","SHW","CME","ETN","AON","DUK","NOC","USB","WM","PNC","ITW","ECL",
        ]


# ── Señal de momentum ─────────────────────────────────────────────────────────

def compute_momentum_top(
    tickers: list[str],
    top_pct : float = 0.05,    # top 5%
    lookback: int   = 12,      # meses
    skip    : int   = 1,       # saltar último mes (evitar reversión)
) -> tuple[list[str], dict[str, float]]:
    """
    Retorna (lista de tickers seleccionados, precios actuales de cierre de AYER).

    Sin lookahead bias:
    - La señal usa precio de hace (skip) meses vs precio de hace (skip+lookback) meses.
    - El precio de ejecución es el cierre de AYER (no el de hoy ni el de la señal).
    """
    print(f"[strategy] Descargando {len(tickers)} tickers (~14 meses de datos diarios)...")

    # Necesitamos 14 meses de datos para calcular señal de 12-1 meses
    # Descargamos en batches de 50 para no sobrecargar yfinance
    all_closes: dict[str, pd.Series] = {}
    batch_size = 50

    for i in range(0, len(tickers), batch_size):
        batch = tickers[i:i + batch_size]
        try:
            raw = yf.download(
                batch, period="15mo", auto_adjust=True,
                progress=False, group_by="ticker"
            )
            if raw.empty:
                continue

            # yfinance puede devolver MultiIndex o índice plano
            if isinstance(raw.columns, pd.MultiIndex):
                for t in batch:
                    try:
                        s = raw[t]["Close"].dropna()
                        if len(s) > 200:
                            all_closes[t] = s
                    except KeyError:
                        pass
            else:
                # Un solo ticker en el batch
                s = raw["Close"].dropna()
                if len(s) > 200 and len(batch) == 1:
                    all_closes[batch[0]] = s
        except Exception as e:
            print(f"  [batch {i//batch_size}] error: {e}")

        time.sleep(0.3)  # respetar rate limit

    if not all_closes:
        print("[strategy] No se pudieron descargar datos")
        return [], {}

    print(f"[strategy] Datos obtenidos para {len(all_closes)} tickers")

    # Construir DataFrame de cierres mensuales
    monthly: dict[str, float] = {}   # momentum score por ticker
    prices_yesterday: dict[str, float] = {}  # precio de ejecución

    for ticker, series in all_closes.items():
        try:
            # Resamplear a fin de mes
            m = series.resample("ME").last().dropna()
            if len(m) < lookback + skip + 2:
                continue

            # Señal: precio de hace `skip` meses / precio de hace `skip+lookback` meses - 1
            # Usamos iloc[-1-skip] y iloc[-1-skip-lookback]
            # Nunca tocamos iloc[-1] (precio del mes actual en curso)
            price_end   = float(m.iloc[-1 - skip])          # hace 1 mes
            price_start = float(m.iloc[-1 - skip - lookback])  # hace 13 meses

            if price_start <= 0:
                continue

            mom = (price_end - price_start) / price_start
            monthly[ticker] = mom

            # Precio de ejecución = último cierre disponible (ayer o hoy premarket)
            prices_yesterday[ticker] = float(series.iloc[-1])

        except (IndexError, ValueError):
            continue

    if not monthly:
        return [], {}

    # Seleccionar top pct
    sorted_tickers = sorted(monthly, key=monthly.get, reverse=True)
    n_select       = max(1, int(len(sorted_tickers) * top_pct))
    selected       = sorted_tickers[:n_select]

    top_scores = {t: monthly[t] for t in selected[:5]}
    print(f"[strategy] Top {n_select} seleccionados (de {len(monthly)} válidos)")
    print(f"[strategy] Top 5 scores: { {t: f'{v:+.1%}' for t,v in top_scores.items()} }")

    return selected, prices_yesterday
