"""Scanner mensual y actualización diaria del bot GameStop squeeze."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from data import get_screener_tickers, get_stock_metrics, get_current_price
from strategy import calculate_sps, should_enter, check_exit, EXIT
from paper_trader import PaperTrader

MAX_TICKERS_TO_ANALYZE = 60  # cuántos tickers del screener analizar


def run_monthly_scan(
    trader: Optional[PaperTrader] = None,
    dry_run: bool = False,
) -> list[dict]:
    """
    Scanner mensual: busca candidatos estilo GameStop y abre posiciones.
    Retorna la lista completa de candidatos evaluados (con SPS y razón).
    """
    if trader is None:
        trader = PaperTrader()

    print(f"\n{'='*65}")
    print(f"  SCANNER MENSUAL — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*65}")
    print(f"  Capital disponible: ${trader.cash:>10,.0f}")
    print(f"  Posiciones abiertas: {len(trader.open_positions)}/3")

    # ── Paso 1: obtener lista de tickers prescritos ────────────────────────
    print("\n[scan] Obteniendo tickers de finviz (short interest >20%, small cap)...")
    tickers = get_screener_tickers(min_short_pct=20)
    print(f"[scan] {len(tickers)} tickers a analizar (tope: {MAX_TICKERS_TO_ANALYZE})")

    # ── Paso 2: puntuar cada candidato ────────────────────────────────────
    candidates: list[dict] = []
    for ticker in tickers[:MAX_TICKERS_TO_ANALYZE]:
        metrics = get_stock_metrics(ticker)
        if not metrics:
            continue
        sps = calculate_sps(metrics)
        enters, reason = should_enter(metrics)
        candidates.append({**metrics, "sps": sps, "enters": enters, "reason": reason})

    candidates.sort(key=lambda x: x["sps"], reverse=True)

    # ── Paso 3: imprimir top candidatos ──────────────────────────────────
    print(f"\n{'─'*65}")
    print(f"  TOP CANDIDATOS (ordenados por SPS)")
    print(f"{'─'*65}")
    print(f"  {'Ticker':<7} {'SPS':>5} {'Short%':>7} {'Float M':>8} {'DTC':>5} {'Vol':>5}  Estado")
    print(f"  {'─'*7} {'─'*5} {'─'*7} {'─'*8} {'─'*5} {'─'*5}  {'─'*20}")
    for c in candidates[:15]:
        status = "✅ ENTRA" if c["enters"] else "❌"
        print(
            f"  {c['ticker']:<7} {c['sps']:>5.1f} "
            f"{c.get('short_float_pct', 0):>6.1f}% "
            f"{c.get('float_shares_m', 0):>7.1f}M "
            f"{c.get('dtc', 0):>4.1f}d "
            f"{c.get('volume_ratio', 0):>4.1f}x  {status}"
        )

    if dry_run:
        print("\n[scan] Modo dry-run: no se abren posiciones.")
        return candidates

    # ── Paso 4: abrir posiciones para los mejores candidatos ──────────────
    qualifying = [c for c in candidates if c["enters"]]
    opened = 0
    for c in qualifying:
        if not trader.can_open_position():
            print("[scan] Portfolio lleno (3 posiciones), no se abren más.")
            break
        pos = trader.open_position(
            ticker=c["ticker"],
            price=c["price"],
            sps_score=c["sps"],
            metrics=c,
        )
        if pos:
            opened += 1

    if opened == 0 and qualifying:
        print(f"[scan] {len(qualifying)} candidatos calificaron pero no se pudo abrir posición.")
    elif opened == 0:
        print("[scan] Ningún candidato superó los filtros de entrada este mes.")
    else:
        print(f"\n[scan] Posiciones nuevas abiertas: {opened}")

    return candidates


def run_daily_update(trader: Optional[PaperTrader] = None) -> None:
    """
    Actualización diaria: refresca precios, evalúa condiciones de salida.
    """
    if trader is None:
        trader = PaperTrader()

    print(f"\n{'='*65}")
    print(f"  DAILY UPDATE — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*65}")

    if not trader.open_positions:
        print("  No hay posiciones abiertas.")
        trader.record_equity()
        summary = trader.get_summary()
        print(f"  Equity: ${summary['total_equity']:,.0f} | Return: {summary['total_return_pct']:+.1%}")
        return

    to_close: list[tuple[str, float, str]] = []

    for ticker in list(trader.open_positions.keys()):
        current_price = get_current_price(ticker)
        if current_price is None:
            print(f"  {ticker}: ⚠ no se pudo obtener precio")
            continue

        metrics = get_stock_metrics(ticker)
        cur_vol = metrics["current_volume"] if metrics else 0
        avg_vol = metrics["avg_volume"] if metrics else 1
        vol_ratio = cur_vol / avg_vol if avg_vol > 0 else 0.0

        trader.update_position(ticker, current_price)
        if vol_ratio >= EXIT["vol_spike_threshold"]:
            trader.mark_volume_spiked(ticker)

        pos = trader.open_positions[ticker]
        should_close, exit_reason = check_exit(
            position=pos,
            current_price=current_price,
            current_volume=cur_vol,
            avg_volume=avg_vol,
            trading_days_held=pos.get("trading_days_held", 0),
        )

        entry = pos["entry_price"]
        pnl_pct = (current_price - entry) / entry
        action = f"→ CIERRA: {exit_reason}" if should_close else "  Hold"
        print(
            f"  {ticker:<6} ${current_price:.2f} (entrada ${entry:.2f}) | "
            f"{pnl_pct:+.1%} | {pos.get('trading_days_held', 0)}d | "
            f"Vol {vol_ratio:.1f}x | {action}"
        )

        if should_close:
            to_close.append((ticker, current_price, exit_reason))

    for ticker, price, reason in to_close:
        trader.close_position(ticker, price, reason)

    equity = trader.record_equity()
    summary = trader.get_summary()
    print(
        f"\n  Equity: ${equity:,.0f} | Return: {summary['total_return_pct']:+.1%} | "
        f"Realizados: ${summary['realized_pnl']:+,.0f}"
    )
