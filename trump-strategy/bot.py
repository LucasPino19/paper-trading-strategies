"""Bot principal de la estrategia Trump Sentiment."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from data import fetch_trump_articles, extract_signals, get_current_price
from strategy import should_enter, check_exit
from paper_trader import PaperTrader


def run_trump_bot(trader: Optional[PaperTrader] = None) -> None:
    """
    Ciclo principal del bot:
      1. Lee noticias recientes de Trump
      2. Extrae señales de compra/venta por ticker
      3. Abre posiciones en compras o cierra en ventas
      4. Actualiza precios y verifica condiciones de salida
    """
    if trader is None:
        trader = PaperTrader()

    print(f"\n{'='*65}")
    print(f"  TRUMP BOT — {datetime.now().strftime('%d/%m/%Y %H:%M')}")
    print(f"{'='*65}")
    print(f"  Capital: ${trader.cash:,.0f} | Posiciones: {len(trader.open_positions)}/3")

    # ── 1. Obtener noticias nuevas ────────────────────────────────────────
    articles = fetch_trump_articles(hours=4)

    if not articles:
        print("[bot] Sin artículos nuevos — solo actualizando posiciones.")
    else:
        # ── 2. Extraer señales ────────────────────────────────────────────
        signals = extract_signals(articles)
        print(f"[bot] {len(signals)} señal(es) detectada(s):")

        for sig in signals:
            icon = "🟢" if sig["action"] == "buy" else "🔴"
            print(
                f"  {icon} {sig['ticker']:5} {sig['action'].upper():4} "
                f"confianza {sig['confidence']:.0%} | "
                f"\"{sig['title'][:55]}...\""
            )

        # ── 3. Ejecutar señales ───────────────────────────────────────────
        for sig in signals:
            ticker = sig["ticker"]

            # Señal negativa → cerrar posición si está abierta
            if sig["action"] == "sell" and ticker in trader.open_positions:
                price = get_current_price(ticker)
                if price:
                    trader.close_position(
                        ticker, price,
                        f"Señal negativa de Trump: {sig['title'][:50]}"
                    )

            # Señal positiva → abrir posición si no está y hay lugar
            elif sig["action"] == "buy" and ticker not in trader.open_positions:
                enters, reason = should_enter(sig)
                if enters and trader.can_open_position():
                    price = get_current_price(ticker)
                    if price:
                        trader.open_position(
                            ticker=ticker,
                            price=price,
                            sps_score=sig["confidence"] * 100,
                            metrics={"short_float_pct": 0, "float_shares_m": 0, "dtc": 0},
                        )
                elif not enters:
                    print(f"  [bot] {ticker} no califica: {reason}")

    # ── 4. Actualizar posiciones abiertas y verificar exits ───────────────
    _update_open_positions(trader)


def _update_open_positions(trader: PaperTrader) -> None:
    to_close = []

    for ticker, pos in list(trader.open_positions.items()):
        price = get_current_price(ticker)
        if not price:
            print(f"  [bot] {ticker}: ⚠ no se pudo obtener precio")
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
        print(
            f"  {ticker:5} ${price:.2f} (entrada ${pos['entry_price']:.2f}) | "
            f"{pnl:+.1%} | {pos.get('trading_days_held', 0)}d | {action}"
        )
        if should_close:
            to_close.append((ticker, price, reason))

    for ticker, price, reason in to_close:
        trader.close_position(ticker, price, reason)

    equity = trader.record_equity()
    summary = trader.get_summary()
    print(f"\n  Equity: ${equity:,.0f} | Return: {summary['total_return_pct']:+.1%}")
