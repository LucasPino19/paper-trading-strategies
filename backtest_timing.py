"""
backtest_timing.py
Simula FVG e ICT a distintos horarios ET para encontrar el mejor momento de ejecución.

Uso: python backtest_timing.py
Descarga ~1 año de datos 1h y hace walk-forward sin look-ahead.
"""
from __future__ import annotations

import importlib.util
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

ROOT = Path(__file__).parent

WATCHLIST = [
    "AAPL", "MSFT", "NVDA", "AMZN", "META",
    "GOOGL", "TSLA", "JPM", "V", "XOM",
    "UNH", "JNJ", "PG", "MA", "HD",
    "BAC", "ABBV", "CVX", "MRK", "PEP",
]

# yfinance 1h para US equities: primer bar a las 9:30 ET, luego cada hora
# 9.5 = 9:30, 10.5 = 10:30, 11.5 = 11:30, etc.
HOURS_ET = [9.5, 10.5, 11.5, 12.5, 13.5, 14.5, 15.5]

INITIAL_CAPITAL = 10_000.0
POSITION_SIZE   = 0.30   # 30% por trade
MAX_POSITIONS   = 3
WARMUP_DAYS     = 30     # días iniciales que se saltean para dar warmup a indicadores


# ── Carga de módulos de estrategia ────────────────────────────────────────────

def load_strat(path: Path):
    name = path.parent.name.replace("-", "_") + "_strat"
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── Descarga de datos ─────────────────────────────────────────────────────────

def download_data(period: str = "1y") -> dict[str, pd.DataFrame]:
    print(f"\nDescargando {len(WATCHLIST)} tickers ({period} de datos 1h)...")
    data: dict[str, pd.DataFrame] = {}
    for i, ticker in enumerate(WATCHLIST, 1):
        try:
            df = yf.download(ticker, period=period, interval="1h",
                             progress=False, auto_adjust=True)
            df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
            df.dropna(inplace=True)
            if df.empty:
                continue
            if df.index.tz is None:
                df.index = df.index.tz_localize("America/New_York")
            else:
                df.index = df.index.tz_convert("America/New_York")
            data[ticker] = df
            print(f"  {i:2}/{len(WATCHLIST)}  {ticker}: {len(df)} barras")
        except Exception as e:
            print(f"  {i:2}/{len(WATCHLIST)}  {ticker}: ERROR — {e}")
    return data


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_bar_at_hour(
    df: pd.DataFrame, day: pd.Timestamp, hour_et: float
) -> pd.Timestamp | None:
    """Último bar en `day` cuyo label es <= hour_et ET."""
    h = int(hour_et)
    m = int((hour_et % 1) * 60)
    try:
        target = pd.Timestamp(
            year=day.year, month=day.month, day=day.day,
            hour=h, minute=m, tz="America/New_York",
        )
    except Exception:
        return None
    day_norm = day.normalize()
    mask = (df.index.normalize() == day_norm) & (df.index <= target)
    subset = df[mask]
    return subset.index[-1] if not subset.empty else None


def top_volume_ticker(data: dict, day: pd.Timestamp) -> str:
    """Ticker con mayor volumen promedio en los 5 días hábiles previos a `day`."""
    vols: dict[str, float] = {}
    day_norm = day.normalize()
    for ticker, df in data.items():
        past = df[df.index.normalize() < day_norm]
        if past.empty:
            continue
        last5 = sorted(past.index.normalize().unique())[-5:]
        mask  = past.index.normalize().isin(last5)
        vols[ticker] = float(past.loc[mask, "Volume"].mean())
    return max(vols, key=vols.get) if vols else "NVDA"


def check_bar(pos: dict, bar: pd.Series, exit_cfg: dict) -> tuple[bool, float, str]:
    """
    Chequea si una vela triggerea salida usando High/Low (más realista que solo Close).
    Actualiza peak_price en pos.
    Retorna (should_exit, exit_price, reason).
    """
    high  = float(bar["High"])
    low   = float(bar["Low"])
    entry = pos["entry_price"]
    peak  = pos.get("peak_price", entry)

    if high > peak:
        pos["peak_price"] = high
        peak = high

    sl = entry * (1.0 + exit_cfg["stop_loss"])   # e.g. 0.94 * entry
    tp = entry * (1.0 + exit_cfg["hard_target"])  # e.g. 1.15 * entry

    if low <= sl:
        return True, sl, "stop"

    if high >= tp:
        return True, tp, "target"

    trail_trigger = exit_cfg.get("trailing_trigger", 9999)
    trail_pct     = exit_cfg.get("trailing_pct", 0.0)
    if (peak - entry) / entry >= trail_trigger:
        trail_stop = peak * (1.0 - trail_pct)
        if low <= trail_stop:
            return True, trail_stop, "trailing"

    return False, float(bar["Close"]), ""


# ── Simulación principal ──────────────────────────────────────────────────────

def simulate(
    strat_name: str,
    strat_mod,
    data: dict[str, pd.DataFrame],
    hour_et: float,
) -> dict:
    """
    Walk-forward completo para (estrategia, hora).
    FVG: elige 1 ticker por volumen diario, abre máx 1 trade por día.
    ICT: escanea todos, abre hasta MAX_POSITIONS (1 por ticker, sorted by score).
    """
    exit_cfg   = strat_mod.EXIT
    time_stop  = exit_cfg["time_stop_days"]

    # Todos los días de trading disponibles en el dataset
    all_days: list[pd.Timestamp] = sorted({
        ts.normalize()
        for df in data.values()
        for ts in df.index
    })
    trading_days = all_days[WARMUP_DAYS:]

    cash       = INITIAL_CAPITAL
    positions: dict[str, dict] = {}    # ticker → {entry_price, shares, peak_price, entry_day, last_bar_ts}
    closed:    list[dict]      = []
    eq_curve:  list[float]     = [INITIAL_CAPITAL]

    for day in trading_days:

        # ── 1. Chequear salidas en posiciones abiertas ────────────────────────
        for ticker in list(positions.keys()):
            if ticker not in data:
                continue
            df_t     = data[ticker]
            bar_now  = get_bar_at_hour(df_t, day, hour_et)
            if bar_now is None:
                continue

            pos      = positions[ticker]
            prev_ts  = pos.get("last_bar_ts")

            # Ventana de barras desde última revisión hasta ahora (inclusive)
            if prev_ts is not None:
                check_bars = df_t[(df_t.index > prev_ts) & (df_t.index <= bar_now)]
            else:
                check_bars = df_t[df_t.index == bar_now]

            exited = False
            for _, bar_row in check_bars.iterrows():
                should_exit, exit_price, reason = check_bar(pos, bar_row, exit_cfg)
                if should_exit:
                    pnl   = (exit_price - pos["entry_price"]) / pos["entry_price"]
                    cash += pos["shares"] * exit_price
                    closed.append({"pnl": pnl, "reason": reason})
                    del positions[ticker]
                    exited = True
                    break

            if exited:
                continue

            # Time stop
            days_held = int(np.busday_count(
                np.datetime64(pos["entry_day"].date()),
                np.datetime64(day.date()),
            ))
            if days_held >= time_stop:
                last_bar = df_t[df_t.index <= bar_now]
                exit_price = float(last_bar.iloc[-1]["Close"]) if not last_bar.empty else pos["entry_price"]
                pnl   = (exit_price - pos["entry_price"]) / pos["entry_price"]
                cash += pos["shares"] * exit_price
                closed.append({"pnl": pnl, "reason": "time"})
                del positions[ticker]
                continue

            # Actualizar last_bar_ts para la próxima iteración
            positions[ticker]["last_bar_ts"] = bar_now

        # ── 2. Buscar señales nuevas ──────────────────────────────────────────
        if len(positions) < MAX_POSITIONS:
            if strat_name == "fvg":
                best_ticker = top_volume_ticker(data, day)
                scan_list   = [] if best_ticker in positions else [best_ticker]
            else:
                # ICT: escanea todos, ordena por score, abre hasta llenar slots
                raw_sigs: list[dict] = []
                for ticker in WATCHLIST:
                    if ticker not in data or ticker in positions:
                        continue
                    df_t    = data[ticker]
                    bar_ts  = get_bar_at_hour(df_t, day, hour_et)
                    if bar_ts is None:
                        continue
                    df_slice = df_t[df_t.index <= bar_ts]
                    if len(df_slice) < 50:
                        continue
                    try:
                        sigs = strat_mod.scan_signals(ticker, df_slice)
                        sigs = [s for s in sigs if s.get("action") == "buy"]
                        raw_sigs.extend(sigs)
                    except Exception:
                        continue
                raw_sigs.sort(key=lambda x: x["score"], reverse=True)
                scan_list = []
                seen = set()
                for sig in raw_sigs:
                    t = sig["ticker"]
                    if t not in seen and t not in positions:
                        scan_list.append(t)
                        seen.add(t)
                    if len(scan_list) + len(positions) >= MAX_POSITIONS:
                        break

            for ticker in scan_list:
                if len(positions) >= MAX_POSITIONS:
                    break
                if ticker not in data:
                    continue
                df_t   = data[ticker]
                bar_ts = get_bar_at_hour(df_t, day, hour_et)
                if bar_ts is None:
                    continue
                df_slice = df_t[df_t.index <= bar_ts]
                if len(df_slice) < 50:
                    continue
                try:
                    sigs = strat_mod.scan_signals(ticker, df_slice)
                    sigs = [s for s in sigs if s.get("action") == "buy"]
                except Exception:
                    continue
                if not sigs:
                    continue

                entry_price = float(df_slice.iloc[-1]["Close"])
                alloc       = cash * POSITION_SIZE
                if alloc < entry_price:
                    continue
                shares      = alloc / entry_price
                cash       -= shares * entry_price
                positions[ticker] = {
                    "entry_price": entry_price,
                    "shares":      shares,
                    "peak_price":  entry_price,
                    "entry_day":   day,
                    "last_bar_ts": bar_ts,
                }

                if strat_name == "fvg":
                    break   # FVG: solo 1 trade por día

        # ── 3. Registrar equity del día ───────────────────────────────────────
        mkt = 0.0
        for ticker, pos in positions.items():
            df_t   = data.get(ticker)
            if df_t is None:
                mkt += pos["shares"] * pos["entry_price"]
                continue
            bar_ts = get_bar_at_hour(df_t, day, hour_et)
            if bar_ts is not None and bar_ts in df_t.index:
                mkt += pos["shares"] * float(df_t.loc[bar_ts, "Close"])
            else:
                mkt += pos["shares"] * pos["entry_price"]
        eq_curve.append(cash + mkt)

    # ── Métricas ──────────────────────────────────────────────────────────────
    final_eq     = eq_curve[-1]
    total_return = (final_eq - INITIAL_CAPITAL) / INITIAL_CAPITAL
    n            = len(closed)
    wins         = sum(1 for t in closed if t["pnl"] > 0)
    win_rate     = wins / n if n else 0.0
    avg_pnl      = float(np.mean([t["pnl"] for t in closed])) if closed else 0.0
    pnls         = [t["pnl"] for t in closed]
    avg_win      = float(np.mean([p for p in pnls if p > 0])) if any(p > 0 for p in pnls) else 0.0
    avg_loss     = float(np.mean([p for p in pnls if p < 0])) if any(p < 0 for p in pnls) else 0.0

    arr  = np.array(eq_curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    dd   = np.where(peak > 0, (arr - peak) / peak, 0.0)
    max_dd = float(dd.min())

    h_int = int(hour_et)
    h_min = int((hour_et % 1) * 60)
    return {
        "hora":          f"{h_int:02d}:{h_min:02d}",
        "trades":        n,
        "win_pct":       win_rate,
        "total_return":  total_return,
        "avg_pnl":       avg_pnl,
        "avg_win":       avg_win,
        "avg_loss":      avg_loss,
        "max_dd":        max_dd,
        "final_equity":  final_eq,
    }


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    fvg_strat = load_strat(ROOT / "fvg-strategy" / "strategy.py")
    ict_strat = load_strat(ROOT / "ict-strategy" / "strategy.py")

    data = download_data(period="1y")
    if not data:
        print("ERROR: no se pudieron descargar datos.")
        return

    strategies = [("FVG", fvg_strat), ("ICT", ict_strat)]
    all_results: dict[str, list[dict]] = {}
    total = len(strategies) * len(HOURS_ET)
    n = 0

    for strat_name, strat_mod in strategies:
        all_results[strat_name] = []
        print(f"\n{'━'*55}")
        print(f"  {strat_name} — simulando {len(HOURS_ET)} horarios...")
        print(f"{'━'*55}")

        for hour in HOURS_ET:
            n += 1
            h_label = f"{int(hour):02d}:{int((hour%1)*60):02d}"
            print(f"  [{n:2}/{total}] {strat_name} @ {h_label} ET...", end=" ", flush=True)
            r = simulate(strat_name.lower(), strat_mod, data, hour)
            all_results[strat_name].append(r)
            print(
                f"trades={r['trades']:2}  win={r['win_pct']:.0%}  "
                f"ret={r['total_return']:+.1%}  dd={r['max_dd']:.1%}"
            )

    # ── Tabla de resultados ───────────────────────────────────────────────────
    print(f"\n\n{'═'*70}")
    print("  RESULTADOS — Retorno total por horario (capital inicial $10,000)")
    print(f"{'═'*70}")

    for strat_name in ["FVG", "ICT"]:
        results = all_results[strat_name]
        best    = max(results, key=lambda r: r["total_return"])

        print(f"\n  {'─'*60}")
        print(f"  {strat_name}")
        print(f"  {'─'*60}")
        print(f"  {'Hora ET':<10} {'Trades':>7} {'Win%':>6} {'Retorno':>9} "
              f"{'AvgPnL':>8} {'AvgWin':>8} {'AvgLoss':>9} {'MaxDD':>7} {'Equity':>10}")
        print(f"  {'─'*60}")

        for r in results:
            marker = " ◀ MEJOR" if r["hora"] == best["hora"] else ""
            print(
                f"  {r['hora']:<10} {r['trades']:>7} {r['win_pct']:>5.0%} "
                f"{r['total_return']:>+8.1%} {r['avg_pnl']:>+7.1%} "
                f"{r['avg_win']:>+7.1%} {r['avg_loss']:>+8.1%} "
                f"{r['max_dd']:>6.1%}  ${r['final_equity']:>8,.0f}{marker}"
            )

        print(f"\n  ✓ Mejor hora para {strat_name}: {best['hora']} ET")
        print(f"    Retorno: {best['total_return']:+.1%} | "
              f"Trades: {best['trades']} | Win rate: {best['win_pct']:.0%} | "
              f"Max DD: {best['max_dd']:.1%}")

    # Guardar CSV
    rows = []
    for strat_name, results in all_results.items():
        for r in results:
            rows.append({"estrategia": strat_name, **r})
    df_out = pd.DataFrame(rows)
    out_path = ROOT / "backtest_timing_results.csv"
    df_out.to_csv(out_path, index=False)
    print(f"\n  Resultados guardados en: {out_path.name}")


if __name__ == "__main__":
    main()
