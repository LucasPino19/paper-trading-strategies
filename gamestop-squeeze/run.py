"""CLI para el bot paper trading GameStop squeeze."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from paper_trader import PaperTrader
from bot import run_monthly_scan, run_daily_update


def cmd_status(trader: PaperTrader) -> None:
    s = trader.get_summary()
    print(f"\n{'='*55}")
    print(f"  ESTADO DEL PORTFOLIO — GameStop Squeeze Bot")
    print(f"{'='*55}")
    print(f"  Capital inicial:     ${s['initial_capital']:>10,.0f}")
    print(f"  Equity total:        ${s['total_equity']:>10,.0f}  ({s['total_return_pct']:+.1%})")
    print(f"  Cash disponible:     ${s['cash']:>10,.0f}")
    print(f"  P&L realizado:       ${s['realized_pnl']:>+10,.0f}")
    print(f"  P&L no realizado:    ${s['unrealized_pnl']:>+10,.0f}")
    print(f"  Posiciones abiertas: {s['open_positions']} / 3")
    print(f"  Trades cerrados:     {s['closed_trades']}")
    if s["closed_trades"]:
        print(f"  Win rate:            {s['win_rate']:.0%}  ({s['wins']}W / {s['losses']}L)")

    if trader.open_positions:
        print(f"\n  {'─'*55}")
        print(f"  POSICIONES ABIERTAS:")
        for ticker, pos in trader.open_positions.items():
            current = pos.get("current_price", pos["entry_price"])
            pnl_pct = (current - pos["entry_price"]) / pos["entry_price"]
            print(
                f"    {ticker:<6} entrada ${pos['entry_price']:.2f} → "
                f"actual ${current:.2f} ({pnl_pct:+.1%}) | "
                f"SPS {pos['sps_score']:.0f} | {pos.get('trading_days_held', 0)}d"
            )
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="GameStop Squeeze Paper Trading Bot",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Comandos disponibles:
  python run.py --scan           Ejecutar scanner mensual (busca candidatos)
  python run.py --scan --dry     Ver candidatos sin abrir posiciones
  python run.py --update         Actualización diaria (precios + exits)
  python run.py --dashboard      Abrir dashboard en el browser
  python run.py --status         Ver resumen del portfolio
  python run.py --reset          Resetear portfolio a $10,000 inicial
        """,
    )
    parser.add_argument("--scan",      action="store_true", help="Scanner mensual")
    parser.add_argument("--update",    action="store_true", help="Update diario")
    parser.add_argument("--dashboard", action="store_true", help="Abrir dashboard")
    parser.add_argument("--status",    action="store_true", help="Ver estado")
    parser.add_argument("--reset",     action="store_true", help="Resetear portfolio")
    parser.add_argument("--dry",       action="store_true", help="Sin abrir posiciones")
    args = parser.parse_args()

    if not any(vars(args).values()):
        parser.print_help()
        return

    trader = PaperTrader()

    if args.reset:
        confirm = input("¿Resetear portfolio a $10,000? Esto borra el historial. (s/n): ")
        if confirm.strip().lower() == "s":
            if os.path.exists(trader.data_file):
                os.remove(trader.data_file)
            print("Portfolio reseteado.")
        return

    if args.status:
        cmd_status(trader)

    if args.scan:
        run_monthly_scan(trader=trader, dry_run=args.dry)

    if args.update:
        run_daily_update(trader=trader)

    if args.dashboard:
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard.py")
        subprocess.run([sys.executable, "-m", "streamlit", "run", script], check=False)


if __name__ == "__main__":
    main()
