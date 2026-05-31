#!/usr/bin/env python3
"""
Strategy Scanner — 100+ estrategias vs SPY
Categorías: Momentum CS, ETF Rotation, Trend Following,
            Dual Momentum, Low Volatility, Seasonal, Contrarian,
            Momentum+Trend
In-sample: 2011–2019 | Out-of-sample: 2020–2026
"""

import os, sys, pickle, warnings, subprocess
import pandas as pd
import numpy as np
import yfinance as yf

warnings.filterwarnings('ignore')

BASE    = os.path.dirname(os.path.abspath(__file__))
DATA    = os.path.join(BASE, 'data')
REPORTS = os.path.join(BASE, 'reports')
os.makedirs(REPORTS, exist_ok=True)

FETCH_START = '2008-01-01'
IS_END      = '2019-12-31'
OOS_START   = '2020-01-01'
WARMUP_START = '2011-01-01'

all_results = []
spy_m       = None   # global, se setea en main()


# ── Métricas ──────────────────────────────────────────────────────────────────

def cagr(r):
    if len(r) < 2: return np.nan
    return (1 + r).prod() ** (12 / len(r)) - 1

def max_dd(r):
    eq = (1 + r).cumprod()
    return (eq / eq.cummax() - 1).min()

def sharpe(r, rf_annual=0.04):
    rf = rf_annual / 12
    ex = r - rf
    return ex.mean() / ex.std() * np.sqrt(12) if ex.std() > 0 else 0.0

def record(name, category, returns):
    r_is  = returns[(returns.index >= WARMUP_START) & (returns.index <= IS_END)]
    r_oos = returns[returns.index >= OOS_START]
    if len(r_is) < 12 or len(r_oos) < 12:
        return
    s_is  = spy_m[(spy_m.index >= r_is.index[0])  & (spy_m.index <= r_is.index[-1])]
    s_oos = spy_m[(spy_m.index >= r_oos.index[0]) & (spy_m.index <= r_oos.index[-1])]
    if len(s_is) < 6 or len(s_oos) < 6:
        return
    all_results.append({
        'Estrategia' : name,
        'Categoría'  : category,
        'CAGR IS'    : cagr(r_is),
        'CAGR OOS'   : cagr(r_oos),
        'Alpha IS'   : cagr(r_is)  - cagr(s_is),
        'Alpha OOS'  : cagr(r_oos) - cagr(s_oos),
        'Sharpe IS'  : sharpe(r_is),
        'Sharpe OOS' : sharpe(r_oos),
        'MaxDD IS'   : max_dd(r_is),
        'MaxDD OOS'  : max_dd(r_oos),
        '$100 1yr'   : 100 * (1 + cagr(r_oos)),
    })


# ── Estrategias ───────────────────────────────────────────────────────────────

def cross_sectional_momentum(prices, lookback, skip, top_pct):
    monthly = prices.resample('ME').last()
    signal  = monthly.shift(skip) / monthly.shift(skip + lookback) - 1
    ret_m   = monthly.pct_change()
    out = []
    for i in range(lookback + skip + 1, len(monthly)):
        date = monthly.index[i]
        sig  = signal.iloc[i-1].dropna()
        if sig.empty: out.append((date, 0.0)); continue
        n    = max(1, int(len(sig) * top_pct))
        top  = sig.nlargest(n).index
        r    = ret_m.loc[date, top].mean()
        out.append((date, float(r) if pd.notna(r) else 0.0))
    return pd.Series([v for _,v in out], index=pd.DatetimeIndex([d for d,_ in out]))


def etf_rotation(prices, lookback, top_n):
    monthly = prices.resample('ME').last().dropna(how='all')
    signal  = monthly.pct_change(lookback)
    ret_m   = monthly.pct_change()
    out = []
    for i in range(lookback + 1, len(monthly)):
        date = monthly.index[i]
        sig  = signal.iloc[i-1].dropna()
        if len(sig) == 0: out.append((date, 0.0)); continue
        sel  = sig.nlargest(min(top_n, len(sig))).index
        r    = ret_m.loc[date, sel].mean()
        out.append((date, float(r) if pd.notna(r) else 0.0))
    return pd.Series([v for _,v in out], index=pd.DatetimeIndex([d for d,_ in out]))


def trend_following(asset, ma_months, safe=None):
    monthly   = asset.resample('ME').last()
    ma        = monthly.rolling(ma_months).mean()
    in_mkt    = monthly.shift(1) > ma.shift(1)
    ret       = monthly.pct_change()
    if safe is not None:
        safe_m  = safe.resample('ME').last()
        safe_r  = safe_m.pct_change().reindex(ret.index, method='ffill').fillna(0)
    else:
        safe_r  = pd.Series(0.04/12, index=ret.index)
    result = ret.where(in_mkt, safe_r).dropna()
    return result


def dual_momentum(spy_p, world_p, bond_p, lookback):
    sm = spy_p.resample('ME').last()
    wm = world_p.resample('ME').last()
    bm = bond_p.resample('ME').last()
    spy_mom  = sm.pct_change(lookback)
    world_mom= wm.pct_change(lookback)
    spy_ret  = sm.pct_change()
    world_ret= wm.pct_change()
    bond_ret = bm.pct_change()
    out = []
    idx = spy_mom.dropna().index
    for date in idx:
        if date not in spy_ret.index: continue
        s, w = spy_mom[date], world_mom.get(date, np.nan)
        if pd.isna(s) or pd.isna(w): continue
        if   s > 0 and s >= w: r = spy_ret.get(date, 0)
        elif w > 0 and w >  s: r = world_ret.get(date, 0)
        else:                  r = bond_ret.get(date, 0)
        out.append((date, float(r) if pd.notna(r) else 0.0))
    return pd.Series([v for _,v in out], index=pd.DatetimeIndex([d for d,_ in out]))


def low_volatility(prices, vol_months, top_pct):
    monthly   = prices.resample('ME').last()
    daily_ret = prices.pct_change()
    # Annualized vol using daily data, window = vol_months * 21 days
    roll_vol  = daily_ret.rolling(vol_months * 21).std() * np.sqrt(252)
    vol_m     = roll_vol.resample('ME').last()
    ret_m     = monthly.pct_change()
    out = []
    for i in range(vol_months + 1, len(monthly)):
        date = monthly.index[i]
        vol  = vol_m.iloc[i-1].dropna()
        if vol.empty: out.append((date, 0.0)); continue
        n    = max(1, int(len(vol) * top_pct))
        sel  = vol.nsmallest(n).index
        r    = ret_m.loc[date, sel].mean()
        out.append((date, float(r) if pd.notna(r) else 0.0))
    return pd.Series([v for _,v in out], index=pd.DatetimeIndex([d for d,_ in out]))


def seasonal(asset, good_months):
    monthly = asset.resample('ME').last()
    ret     = monthly.pct_change().dropna()
    result  = ret.where(ret.index.month.isin(good_months), 0.04/12)
    return result


def contrarian(prices, lookback, bottom_pct):
    monthly = prices.resample('ME').last()
    signal  = monthly.shift(1) / monthly.shift(1 + lookback) - 1
    ret_m   = monthly.pct_change()
    out = []
    for i in range(lookback + 2, len(monthly)):
        date = monthly.index[i]
        sig  = signal.iloc[i-1].dropna()
        if sig.empty: out.append((date, 0.0)); continue
        n    = max(1, int(len(sig) * bottom_pct))
        bot  = sig.nsmallest(n).index
        r    = ret_m.loc[date, bot].mean()
        out.append((date, float(r) if pd.notna(r) else 0.0))
    return pd.Series([v for _,v in out], index=pd.DatetimeIndex([d for d,_ in out]))


def momentum_trend_filter(sp500_prices, spy_p, lookback, top_pct, ma_months):
    monthly  = sp500_prices.resample('ME').last()
    signal   = monthly.shift(1) / monthly.shift(1 + lookback) - 1
    ret_m    = monthly.pct_change()
    spy_m_p  = spy_p.resample('ME').last()
    spy_ma   = spy_m_p.rolling(ma_months).mean()
    above_ma = spy_m_p.shift(1) > spy_ma.shift(1)
    out = []
    for i in range(max(lookback, ma_months) + 2, len(monthly)):
        date = monthly.index[i]
        if date not in above_ma.index or not above_ma.loc[date]:
            out.append((date, 0.04/12)); continue
        sig = signal.iloc[i-1].dropna()
        if sig.empty: out.append((date, 0.0)); continue
        n   = max(1, int(len(sig) * top_pct))
        top = sig.nlargest(n).index
        r   = ret_m.loc[date, top].mean()
        out.append((date, float(r) if pd.notna(r) else 0.0))
    return pd.Series([v for _,v in out], index=pd.DatetimeIndex([d for d,_ in out]))


def momentum_low_vol_combo(sp500_prices, lookback, top_pct, vol_months):
    """Selecciona por momentum SOLO entre las acciones de baja volatilidad."""
    monthly   = sp500_prices.resample('ME').last()
    signal    = monthly.shift(1) / monthly.shift(1 + lookback) - 1
    ret_m     = monthly.pct_change()
    daily_ret = sp500_prices.pct_change()
    roll_vol  = daily_ret.rolling(vol_months * 21).std()
    vol_m     = roll_vol.resample('ME').last()
    out = []
    for i in range(max(lookback, vol_months) + 2, len(monthly)):
        date = monthly.index[i]
        sig  = signal.iloc[i-1].dropna()
        vol  = vol_m.iloc[i-1].dropna()
        if sig.empty or vol.empty: out.append((date, 0.0)); continue
        # Keep only low-vol half, then pick top momentum within that
        low_vol_universe = vol.nsmallest(int(len(vol) * 0.50)).index
        sig_filtered = sig[sig.index.isin(low_vol_universe)].dropna()
        if sig_filtered.empty: out.append((date, 0.0)); continue
        n   = max(1, int(len(sig_filtered) * top_pct))
        top = sig_filtered.nlargest(n).index
        r   = ret_m.loc[date, top].mean()
        out.append((date, float(r) if pd.notna(r) else 0.0))
    return pd.Series([v for _,v in out], index=pd.DatetimeIndex([d for d,_ in out]))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    global spy_m

    print(f"\n{'═'*70}")
    print("  STRATEGY SCANNER — 100+ Estrategias vs SPY")
    print(f"{'═'*70}\n")

    # ── Cargar precios S&P 500 (cache de run.py) ──────────────────────────────
    prices_path = os.path.join(DATA, 'prices.pkl')
    if not os.path.exists(prices_path):
        print("ERROR: No encontré precios cacheados.")
        print("       Corré primero: python3 run.py")
        sys.exit(1)

    print("Cargando datos cacheados del S&P 500...")
    with open(prices_path, 'rb') as f:
        sp500 = pickle.load(f)
    print(f"  {sp500.shape[1]} acciones × {len(sp500)} días")

    # ── Descargar / cargar ETFs ───────────────────────────────────────────────
    etf_list = [
        'SPY','QQQ','IWM','EFA','EEM','TLT','GLD','VNQ','SHY','AGG','VEA',
        'XLK','XLF','XLE','XLV','XLI','XLC','XLY','XLP','XLU','XLRE','XLB',
        'DIA','MDY','BND','VT','ACWI'
    ]
    etf_path = os.path.join(DATA, 'etf_prices.pkl')
    if os.path.exists(etf_path):
        print("Cargando ETFs del cache...")
        with open(etf_path, 'rb') as f:
            etf = pickle.load(f)
    else:
        print("Descargando ETFs...")
        raw = yf.download(etf_list, start=FETCH_START, auto_adjust=True, progress=True)
        etf = raw['Close']
        if isinstance(etf.columns, pd.MultiIndex):
            etf.columns = etf.columns.get_level_values(0)
        with open(etf_path, 'wb') as f:
            pickle.dump(etf, f)
    print(f"  {etf.shape[1]} ETFs disponibles")

    def g(t): return etf[t].dropna() if t in etf.columns else None
    def has(t): return t in etf.columns and not etf[t].dropna().empty

    spy_daily = g('SPY')
    spy_m     = spy_daily.resample('ME').last().pct_change().dropna()
    spy_m.name = 'SPY'

    n = 0
    total_errors = 0

    def safe_record(name, cat, fn, *args):
        nonlocal n, total_errors
        try:
            r = fn(*args)
            record(name, cat, r)
            n += 1
        except Exception:
            total_errors += 1

    # ═══════════════════════════════════════════════════════════════════════════
    # A. CROSS-SECTIONAL MOMENTUM  (4×2×4 = 32)
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n[A] Cross-sectional Momentum S&P 500 (32 variantes)...")
    for lb in [3, 6, 9, 12]:
        for sk in [0, 1]:
            for tp in [0.05, 0.10, 0.20, 0.30]:
                safe_record(f"MOM_L{lb}_S{sk}_T{int(tp*100)}", "Momentum CS",
                            cross_sectional_momentum, sp500, lb, sk, tp)
    print(f"  completadas → total acumulado: {n}")

    # ═══════════════════════════════════════════════════════════════════════════
    # B. ETF ROTATION  (~36)
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n[B] ETF Rotation (3 universos × 4 lookbacks × 3 top_n = 36)...")
    universes = {
        'MultiAsset': [t for t in ['SPY','QQQ','IWM','EFA','EEM','TLT','GLD','VNQ'] if g(t) is not None],
        'GTAA'      : [t for t in ['SPY','QQQ','TLT','GLD','SHY']               if g(t) is not None],
        'Sectores'  : [t for t in ['XLK','XLF','XLE','XLV','XLI','XLY','XLP','XLU','XLRE','XLB'] if g(t) is not None],
    }
    for uname, tickers in universes.items():
        if len(tickers) < 2: continue
        u_prices = etf[tickers].dropna(how='all')
        for lb in [1, 3, 6, 12]:
            for top_n in [1, 2, 3]:
                safe_record(f"ETF_{uname}_L{lb}_top{top_n}", "ETF Rotation",
                            etf_rotation, u_prices, lb, top_n)
    print(f"  completadas → total acumulado: {n}")

    # ═══════════════════════════════════════════════════════════════════════════
    # C. TREND FOLLOWING  (8 MA × 3 assets × 2 safe = ~48, pero filtramos)
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n[C] Trend Following (~24)...")
    ma_periods = [3, 6, 8, 10, 12, 18]
    for ma in ma_periods:
        safe_record(f"TREND_SPY_MA{ma}_cash",  "Trend Following", trend_following, spy_daily, ma, None)
        if has('TLT'):
            safe_record(f"TREND_SPY_MA{ma}_TLT", "Trend Following", trend_following, spy_daily, ma, g('TLT'))
        if has('QQQ'):
            safe_record(f"TREND_QQQ_MA{ma}_cash","Trend Following", trend_following, g('QQQ'), ma, None)
        if has('QQQ') and has('TLT'):
            safe_record(f"TREND_QQQ_MA{ma}_TLT", "Trend Following", trend_following, g('QQQ'), ma, g('TLT'))
    print(f"  completadas → total acumulado: {n}")

    # ═══════════════════════════════════════════════════════════════════════════
    # D. DUAL MOMENTUM  (4 lookbacks × 2 safe × 2 world ETFs = 16)
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n[D] Dual Momentum...")
    world_etfs = [(t, g(t)) for t in ['EFA','VT','ACWI'] if has(t)]
    safe_etfs  = [(t, g(t)) for t in ['AGG','TLT','SHY'] if has(t)]
    for lb in [3, 6, 9, 12]:
        for wname, w in world_etfs[:2]:
            for sname, s in safe_etfs[:2]:
                safe_record(f"DUALMOM_L{lb}_{wname}_{sname}", "Dual Momentum",
                            dual_momentum, spy_daily, w, s, lb)
    print(f"  completadas → total acumulado: {n}")

    # ═══════════════════════════════════════════════════════════════════════════
    # E. LOW VOLATILITY  (3 ventanas × 3 top_pct = 9)
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n[E] Low Volatility S&P 500...")
    for vm in [3, 6, 12]:
        for tp in [0.10, 0.20, 0.30]:
            safe_record(f"LOWVOL_V{vm}m_T{int(tp*100)}", "Low Volatility",
                        low_volatility, sp500, vm, tp)
    print(f"  completadas → total acumulado: {n}")

    # ═══════════════════════════════════════════════════════════════════════════
    # F. SEASONAL  (10 combinaciones)
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n[F] Seasonal...")
    seasons = {
        'NovAbr_BestHalf'   : [11,12,1,2,3,4],
        'OctMar_BestHalf'   : [10,11,12,1,2,3],
        'AvoidSep'          : [1,2,3,4,5,6,7,8,10,11,12],
        'AvoidAgoSep'       : [1,2,3,4,5,6,7,10,11,12],
        'Q4'                : [10,11,12],
        'Q1'                : [1,2,3],
        'Q4_Q1'             : [10,11,12,1,2,3],
        'SoloNovDicEne'     : [11,12,1],
        'EvitarMayJun'      : [1,2,3,4,7,8,9,10,11,12],
        'EvitarQ3'          : [1,2,3,4,5,6,10,11,12],
    }
    for sname, months in seasons.items():
        safe_record(f"SEASONAL_{sname}", "Seasonal",
                    seasonal, spy_daily, months)
    print(f"  completadas → total acumulado: {n}")

    # ═══════════════════════════════════════════════════════════════════════════
    # G. CONTRARIAN  (3 lookbacks × 2 bottom_pct = 6)
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n[G] Contrarian / Mean Reversion...")
    for lb in [1, 3, 6]:
        for bp in [0.10, 0.20]:
            safe_record(f"CONTRARIAN_L{lb}_B{int(bp*100)}", "Contrarian",
                        contrarian, sp500, lb, bp)
    print(f"  completadas → total acumulado: {n}")

    # ═══════════════════════════════════════════════════════════════════════════
    # H. MOMENTUM + TREND FILTER  (2 lookbacks × 2 top_pct × 3 MA = 12)
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n[H] Momentum + Trend Filter...")
    for lb in [6, 12]:
        for tp in [0.10, 0.20]:
            for ma in [6, 10, 12]:
                safe_record(f"MOM_TREND_L{lb}_T{int(tp*100)}_MA{ma}", "Momentum+Trend",
                            momentum_trend_filter, sp500, spy_daily, lb, tp, ma)
    print(f"  completadas → total acumulado: {n}")

    # ═══════════════════════════════════════════════════════════════════════════
    # I. MOMENTUM + LOW VOL COMBO  (2 lookbacks × 2 top_pct × 2 vol = 8)
    # ═══════════════════════════════════════════════════════════════════════════
    print("\n[I] Momentum dentro de universo Low Volatility...")
    for lb in [6, 12]:
        for tp in [0.10, 0.20]:
            for vm in [3, 6]:
                safe_record(f"MOM_LOWVOL_L{lb}_T{int(tp*100)}_V{vm}", "Mom+LowVol",
                            momentum_low_vol_combo, sp500, lb, tp, vm)
    print(f"  completadas → total acumulado: {n}")

    # ── Resultados ────────────────────────────────────────────────────────────
    if not all_results:
        print("No se generaron resultados.")
        return

    df = pd.DataFrame(all_results)
    df = df.sort_values('Alpha OOS', ascending=False).reset_index(drop=True)
    df.index += 1

    # Guardar CSV completo
    csv_path = os.path.join(REPORTS, 'all_strategies.csv')
    df.to_csv(csv_path)
    print(f"\n\nResultados completos guardados → {csv_path}")

    # ── Imprimir ranking ──────────────────────────────────────────────────────
    sep = "─" * 112
    print(f"\n{'═'*112}")
    print(f"  RANKING — {len(df)} estrategias testeadas vs SPY  |  Ordenadas por Alpha OUT-OF-SAMPLE (2020–2026)")
    print(f"{'═'*112}")
    print(f"{'#':<5} {'Estrategia':<38} {'Categoría':<16} {'CAGR OOS':>9} {'Alpha OOS':>10} {'Sharpe OOS':>11} {'MaxDD OOS':>10} {'$100→1yr':>9}")
    print(sep)

    for rank, row in df.iterrows():
        flag = "✅" if row['Alpha OOS'] > 0.01 else ("〰" if row['Alpha OOS'] > 0 else "❌")
        print(f"{rank:<5} {row['Estrategia']:<38} {row['Categoría']:<16} "
              f"{row['CAGR OOS']*100:>8.1f}% {row['Alpha OOS']*100:>9.1f}%  "
              f"{row['Sharpe OOS']:>10.3f}  {row['MaxDD OOS']*100:>8.1f}%   "
              f"{flag} ${row['$100 1yr']:.2f}")

    # ── Resumen por categoría ─────────────────────────────────────────────────
    print(f"\n{'═'*70}")
    print("  RESUMEN POR CATEGORÍA")
    print(f"{'═'*70}")
    print(f"{'Categoría':<20} {'n':>4} {'Alpha med':>10} {'Alpha best':>11} {'% beat SPY':>11}")
    print("─" * 60)
    summary = df.groupby('Categoría').agg(
        n         = ('Alpha OOS', 'count'),
        med_alpha = ('Alpha OOS', 'median'),
        best      = ('Alpha OOS', 'max'),
        pct_beat  = ('Alpha OOS', lambda x: (x > 0).mean() * 100)
    ).sort_values('med_alpha', ascending=False)
    for cat, row in summary.iterrows():
        print(f"{cat:<20} {int(row['n']):>4} {row['med_alpha']*100:>9.1f}%  "
              f"{row['best']*100:>9.1f}%   {row['pct_beat']:>8.0f}%")

    # ── Top 5 por categoría ───────────────────────────────────────────────────
    print(f"\n{'═'*70}")
    print("  TOP 3 POR CATEGORÍA (Alpha OOS)")
    print(f"{'═'*70}")
    for cat in summary.index:
        top3 = df[df['Categoría'] == cat].head(3)
        print(f"\n  {cat}:")
        for _, row in top3.iterrows():
            print(f"    {row['Estrategia']:<40} Alpha OOS: {row['Alpha OOS']*100:+.1f}%  "
                  f"$100→${row['$100 1yr']:.2f}")

    # ── Veredicto final ───────────────────────────────────────────────────────
    beat_spy = (df['Alpha OOS'] > 0).sum()
    best     = df.iloc[0]
    print(f"\n{'═'*70}")
    print("  VEREDICTO FINAL")
    print(f"{'═'*70}")
    print(f"  {beat_spy} de {len(df)} estrategias le ganaron al SPY out-of-sample")
    print(f"  Mejor estrategia: {best['Estrategia']}")
    print(f"    CAGR: {best['CAGR OOS']*100:.1f}%  |  Alpha: {best['Alpha OOS']*100:+.1f}%  |  $100 → ${best['$100 1yr']:.2f}/año")
    print(f"\n  ⚠️  Survivorship bias: alpha real ~2-3% menor en las estrategias de S&P 500")
    print(f"{'═'*70}\n")

    # Abrir CSV
    subprocess.run(['open', csv_path], capture_output=True)


if __name__ == '__main__':
    main()
