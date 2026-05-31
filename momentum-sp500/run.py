#!/usr/bin/env python3
"""
Momentum SP500 — Backtest Cuantitativo
---------------------------------------
Estrategia: cada mes, comprar las top 20% acciones del S&P 500
por momentum de 12 meses (salteando el último mes para evitar reversión).

In-sample:      2011–2019  (para diseñar y optimizar)
Out-of-sample:  2020–2026  (datos que la estrategia nunca vio)
Benchmark:      SPY (buy & hold)

ADVERTENCIA: Survivorship bias — solo se incluyen acciones que
sobrevivieron hasta 2026. El alpha real es ~2-3% menor.
"""

import os, sys, pickle, subprocess, warnings
import pandas as pd
import numpy as np
import yfinance as yf

warnings.filterwarnings('ignore')

BASE    = os.path.dirname(os.path.abspath(__file__))
DATA    = os.path.join(BASE, 'data')
REPORTS = os.path.join(BASE, 'reports')

LOOKBACK  = 12    # meses de ventana momentum
SKIP      = 1     # saltar último mes (evita reversión de corto plazo)
TOP_PCT   = 0.20  # seleccionar top 20%
IS_END    = '2019-12-31'
OOS_START = '2020-01-01'
FETCH_START = '2009-01-01'


# ── Datos ─────────────────────────────────────────────────────────────────────

def get_tickers():
    path = os.path.join(DATA, 'tickers.pkl')
    if os.path.exists(path):
        with open(path, 'rb') as f:
            return pickle.load(f)
    print("Obteniendo lista S&P 500 de Wikipedia...")
    import requests
    from io import StringIO
    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    resp = requests.get(url, headers=headers, timeout=15)
    resp.raise_for_status()
    df = pd.read_html(StringIO(resp.text))[0]
    tickers = df['Symbol'].str.replace('.', '-', regex=False).tolist()
    with open(path, 'wb') as f:
        pickle.dump(tickers, f)
    print(f"  {len(tickers)} tickers guardados")
    return tickers


def get_prices(tickers):
    path = os.path.join(DATA, 'prices.pkl')
    if os.path.exists(path):
        print("Cargando precios del cache local...")
        with open(path, 'rb') as f:
            return pickle.load(f)

    print(f"Descargando {len(tickers)} acciones (tarda ~5 minutos)...")
    raw = yf.download(tickers, start=FETCH_START, auto_adjust=True, progress=True)
    prices = raw['Close'] if isinstance(raw.columns, pd.MultiIndex) else raw

    # Mantener solo acciones con al menos 80% de datos disponibles
    min_obs = int(0.80 * len(prices))
    prices = prices.dropna(thresh=min_obs, axis=1)

    with open(path, 'wb') as f:
        pickle.dump(prices, f)
    print(f"  Cache guardado: {prices.shape[1]} acciones × {len(prices)} días")
    return prices


# ── Backtest ──────────────────────────────────────────────────────────────────

def backtest(prices):
    monthly = prices.resample('ME').last()
    # Señal: precio hace (SKIP + LOOKBACK) meses vs precio hace SKIP meses
    signal = monthly.shift(SKIP) / monthly.shift(SKIP + LOOKBACK) - 1
    monthly_ret = monthly.pct_change()

    results = []
    for i in range(LOOKBACK + SKIP + 1, len(monthly)):
        date = monthly.index[i]
        sig  = signal.iloc[i - 1].dropna()
        if sig.empty:
            results.append((date, 0.0))
            continue
        n_top    = max(1, int(len(sig) * TOP_PCT))
        selected = sig.nlargest(n_top).index
        ret      = monthly_ret.loc[date, selected].mean()
        results.append((date, float(ret) if not np.isnan(ret) else 0.0))

    returns = pd.Series(
        [r for _, r in results],
        index=pd.DatetimeIndex([d for d, _ in results]),
        name='Momentum'
    )
    return returns


# ── Métricas ──────────────────────────────────────────────────────────────────

def cagr(r):
    return (1 + r).prod() ** (12 / len(r)) - 1

def max_drawdown(r):
    eq = (1 + r).cumprod()
    return (eq / eq.cummax() - 1).min()

def sharpe(r, rf_annual=0.04):
    rf = rf_annual / 12
    ex = r - rf
    return ex.mean() / ex.std() * np.sqrt(12) if ex.std() > 0 else 0.0

def print_stats(label, r_strat, r_bench):
    end = min(r_strat.index[-1], r_bench.index[-1])
    rs  = r_strat[r_strat.index <= end]
    rb  = r_bench[r_bench.index <= end]
    rb  = rb[rb.index >= rs.index[0]]

    alpha = cagr(rs) - cagr(rb)
    print(f"\n  {label}")
    print(f"    {'Momentum CAGR':<22} {cagr(rs)*100:+7.2f}%")
    print(f"    {'SPY CAGR':<22} {cagr(rb)*100:+7.2f}%")
    print(f"    {'Alpha anual':<22} {alpha*100:+7.2f}%")
    print(f"    {'Sharpe':<22}  {sharpe(rs):7.3f}")
    print(f"    {'Max Drawdown':<22} {max_drawdown(rs)*100:7.2f}%")
    print(f"    {'$100 → 1 año':<22} ${100 * (1 + cagr(rs)):7.2f}")
    return alpha


# ── Reporte HTML ──────────────────────────────────────────────────────────────

def generate_report(returns, benchmark, path):
    try:
        import quantstats as qs
        qs.reports.html(
            returns, benchmark=benchmark,
            output=path,
            title='Momentum SP500 vs SPY'
        )
        return True
    except Exception as e:
        print(f"  Error generando HTML: {e}")
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    sep = "─" * 60
    print(f"\n{'═'*60}")
    print("  MOMENTUM SP500 — Backtest Cuantitativo")
    print(f"{'═'*60}\n")

    tickers = get_tickers()
    prices  = get_prices(tickers)

    print("\nDescargando SPY como benchmark...")
    spy_daily  = yf.download('SPY', start=FETCH_START, auto_adjust=True, progress=False)['Close'].squeeze()
    spy_m      = spy_daily.resample('ME').last().pct_change().dropna()
    spy_m.name = 'SPY'

    print("Corriendo backtest (puede tardar ~1 minuto)...")
    ret_full = backtest(prices)
    ret_full = ret_full[ret_full.index.year >= 2011]

    # In-sample
    print(f"\n{sep}")
    print("  RESULTADOS")
    print(sep)

    ret_is   = ret_full[ret_full.index <= IS_END]
    spy_is   = spy_m[(spy_m.index >= ret_is.index[0]) & (spy_m.index <= IS_END)]
    alpha_is = print_stats("IN-SAMPLE  2011–2019  (datos de entrenamiento)", ret_is, spy_is)

    # Out-of-sample
    ret_oos   = ret_full[ret_full.index >= OOS_START]
    spy_oos   = spy_m[spy_m.index >= OOS_START]
    alpha_oos = print_stats("OUT-OF-SAMPLE  2020–2026  (datos nuevos, la prueba real)", ret_oos, spy_oos)

    # Full
    spy_full   = spy_m[spy_m.index >= ret_full.index[0]]
    alpha_full = print_stats("PERÍODO COMPLETO  2011–2026", ret_full, spy_full)

    # Veredicto
    print(f"\n{sep}")
    print("  VEREDICTO")
    print(sep)
    if alpha_is > 0 and alpha_oos > 0:
        print(f"  ✅ Alpha POSITIVO en ambos períodos.")
        print(f"     La estrategia funciona en datos que nunca vio.")
    elif alpha_is > 0 and alpha_oos <= 0:
        print(f"  ⚠️  Alpha positivo en-sample pero NEGATIVO out-of-sample.")
        print(f"     Posible overfitting. No deployar todavía.")
    else:
        print(f"  ❌ No hay alpha consistente. La estrategia no le gana al S&P.")

    print(f"\n  ADVERTENCIA: Survivorship bias presente.")
    print(f"  Solo incluye acciones que sobrevivieron hasta 2026.")
    print(f"  El alpha real es aproximadamente 2-3% menor.")

    # Reporte HTML
    print(f"\n{sep}")
    report_path = os.path.join(REPORTS, 'momentum_sp500.html')
    print(f"  Generando reporte HTML...")
    ok = generate_report(ret_full, spy_full, report_path)
    if ok:
        print(f"  ✅ Reporte guardado: {report_path}")
        subprocess.run(['open', report_path], capture_output=True)
        print(f"     Abriendo en el navegador...")
    print(f"{'═'*60}\n")


if __name__ == '__main__':
    main()
