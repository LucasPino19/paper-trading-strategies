"""
Test suite — verifica que todos los bots arrancan, descargan datos,
ranquean el universo, generan señales y calculan salidas correctamente.
"""
import warnings; warnings.filterwarnings("ignore")

import sys, os, importlib.util, traceback
from datetime import datetime

import yfinance as yf
import pandas as pd

BASE = os.path.dirname(os.path.abspath(__file__))

STRATEGIES = [
    # (folder, interval, period, nombre)
    ("fvg-strategy",          "1h", "3mo", "FVG + VWAP"),
    ("ict-strategy",          "1h", "3mo", "ICT Order Blocks"),
    ("gap-strategy",          "1h", "3mo", "Gap & Go"),
    ("orb-breakout-strategy", "1h", "3mo", "ORB + Breakout"),
    ("breakout50d-strategy",  "1d", "1y",  "Breakout 50d"),
    ("momentum-strategy",     "1h", "3mo", "Momentum 10d"),
    ("bb-bounce-strategy",    "1d", "1y",  "BB Lower Bounce"),
    ("pullback-strategy",     "1d", "1y",  "Pullback EMA50"),
]

TEST_TICKER = {"1h": "NVDA", "1d": "SPY"}

# ── Helpers ───────────────────────────────────────────────────────────────────

def load_mod(folder, filename):
    """Carga un módulo desde una subcarpeta sin contaminar sys.modules."""
    path = os.path.join(BASE, folder, filename)
    name = f"_test_{folder}_{filename[:-3]}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    folder_path = os.path.join(BASE, folder)
    sys.path.insert(0, folder_path)
    try:
        spec.loader.exec_module(mod)
    finally:
        if folder_path in sys.path:
            sys.path.remove(folder_path)
    return mod

def download(ticker, interval, period):
    df = yf.download(ticker, period=period, interval=interval,
                     progress=False, auto_adjust=True)
    df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    df.dropna(inplace=True)
    return df

def check(label, condition, detail=""):
    if condition:
        print(f"  ✓  {label}" + (f"  ({detail})" if detail else ""))
        return True
    else:
        print(f"  ✗  {label}" + (f"  → {detail}" if detail else ""))
        return False

# ── Test runner ───────────────────────────────────────────────────────────────

def test_strategy(folder, interval, period, name, test_dfs):
    passed = failed = 0

    def run(fn):
        nonlocal passed, failed
        try:
            ok = fn()
            if ok:
                passed += 1
            else:
                failed += 1
        except Exception as e:
            print(f"  ✗  EXCEPCIÓN: {e}")
            traceback.print_exc()
            failed += 1

    # ── 1. Import strategy.py ────────────────────────────────────────────
    strat = None
    def t_import_strat():
        nonlocal strat
        strat = load_mod(folder, "strategy.py")
        return check("strategy.py importado", strat is not None)
    run(t_import_strat)
    if strat is None:
        return passed, failed

    # ── 2. Import bot.py ─────────────────────────────────────────────────
    bot = None
    def t_import_bot():
        nonlocal bot
        bot = load_mod(folder, "bot.py")
        has_rank  = hasattr(bot, "rankear_universe")
        has_desc  = hasattr(bot, "descargar_datos")
        has_price = hasattr(bot, "get_current_price")
        return check("bot.py importado",
                     all([has_rank, has_desc, has_price]),
                     f"rankear_universe={'✓' if has_rank else '✗'}  "
                     f"descargar_datos={'✓' if has_desc else '✗'}  "
                     f"get_current_price={'✓' if has_price else '✗'}")
    run(t_import_bot)
    if bot is None:
        return passed, failed

    # ── 3. rankear_universe ──────────────────────────────────────────────
    ranked = []
    def t_rank():
        nonlocal ranked
        ranked = bot.rankear_universe()
        return check("rankear_universe()",
                     isinstance(ranked, list) and len(ranked) > 0,
                     f"{len(ranked)} instrumentos → {', '.join(ranked[:3])}")
    run(t_rank)

    # ── 4. descargar_datos ───────────────────────────────────────────────
    def t_download():
        ticker = TEST_TICKER[interval]
        df = bot.descargar_datos(ticker)
        return check("descargar_datos()",
                     not df.empty and {"Open","High","Low","Close","Volume"}.issubset(df.columns),
                     f"{ticker} {interval} → {len(df)} barras, columnas: {list(df.columns)}")
    run(t_download)

    # ── 5. scan_signals ──────────────────────────────────────────────────
    def t_signals():
        ticker = TEST_TICKER[interval]
        df = test_dfs[interval]
        sigs = strat.scan_signals(ticker, df)
        estado = f"{len(sigs)} señal(es)" if sigs else "sin señal hoy (normal fuera de horario)"
        return check("scan_signals()", isinstance(sigs, list), estado)
    run(t_signals)

    # ── 6. check_exit — stop loss ────────────────────────────────────────
    def t_exit_stop():
        pos = {"entry_price": 100.0, "peak_price": 100.0}
        ok, reason = strat.check_exit(pos, 85.0, 1)    # -15% siempre cierra
        return check("check_exit() stop loss", ok, reason)
    run(t_exit_stop)

    # ── 7. check_exit — hold ─────────────────────────────────────────────
    def t_exit_hold():
        pos = {"entry_price": 100.0, "peak_price": 103.0}
        ok, _ = strat.check_exit(pos, 101.5, 1)        # en ganancia, poco tiempo
        return check("check_exit() hold correcto", not ok, "no cierra prematuramente")
    run(t_exit_hold)

    # ── 8. check_exit — time stop ────────────────────────────────────────
    def t_exit_time():
        pos = {"entry_price": 100.0, "peak_price": 100.5}
        ok, reason = strat.check_exit(pos, 100.1, 999) # 999 días siempre cierra
        return check("check_exit() time stop", ok, reason)
    run(t_exit_time)

    # ── 9. PaperTrader ───────────────────────────────────────────────────
    def t_trader():
        folder_path = os.path.join(BASE, folder)
        sys.path.insert(0, folder_path)
        try:
            import importlib
            pt_mod = importlib.import_module("paper_trader")
            importlib.reload(pt_mod)   # fuerza recarga desde la carpeta correcta
            trader = pt_mod.PaperTrader()
            s = trader.get_summary()
            return check("PaperTrader()",
                         "total_equity" in s,
                         f"equity ${s['total_equity']:,.0f} | "
                         f"cash ${s['cash']:,.0f} | "
                         f"trades {s['closed_trades']}")
        finally:
            if folder_path in sys.path:
                sys.path.remove(folder_path)
    run(t_trader)

    return passed, failed


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    print("\n" + "="*68)
    print(f"  TEST SUITE — Paper Trading Bots")
    print(f"  {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print("="*68)

    # Pre-descargar datos de prueba una sola vez
    print("\n[setup] Descargando datos de prueba...")
    test_dfs = {}
    for interval, period in [("1h", "3mo"), ("1d", "1y")]:
        ticker = TEST_TICKER[interval]
        df = download(ticker, interval, period)
        test_dfs[interval] = df
        status = f"{len(df)} barras" if not df.empty else "VACÍO"
        print(f"  {ticker} {interval} ({period}): {status}")

    total_passed = total_failed = 0

    for folder, interval, period, name in STRATEGIES:
        print(f"\n{'─'*68}")
        print(f"  🧪  {name}  [{folder}]")
        print(f"{'─'*68}")
        p, f = test_strategy(folder, interval, period, name, test_dfs)
        total_passed += p
        total_failed += f
        status = "✅ PASÓ" if f == 0 else f"❌ {f} FALLO(S)"
        print(f"  → {p}/{p+f} tests  {status}")

    print(f"\n{'='*68}")
    grade = "✅ TODOS LOS TESTS PASARON" if total_failed == 0 else f"❌ {total_failed} FALLOS"
    print(f"  {grade}  —  {total_passed} pasados / {total_failed} fallados")
    print(f"{'='*68}\n")
    return total_failed == 0


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
