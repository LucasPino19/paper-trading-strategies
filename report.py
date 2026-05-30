"""
Reporte diario consolidado — lee todos los portfolio.json y genera
reports/YYYY-MM-DD.md con lo que hizo cada bot durante el día.
"""
import json, os
from datetime import date, datetime

BASE  = os.path.dirname(os.path.abspath(__file__))
TODAY = date.today().isoformat()

STRATEGIES = [
    ("fvg-strategy",          "📐 FVG + VWAP"),
    ("ict-strategy",          "🧱 ICT Order Blocks"),
    ("gap-strategy",          "🚀 Gap & Go"),
    ("orb-breakout-strategy", "📊 ORB + Breakout"),
    ("breakout50d-strategy",  "📈 Breakout 50d"),
    ("momentum-strategy",     "⚡ Momentum 10d"),
    ("bb-bounce-strategy",    "🎯 BB Lower Bounce"),
    ("pullback-strategy",     "↩️  Pullback EMA50"),
    ("gamestop-squeeze",      "🎮 GameStop Squeeze"),
    ("trump-strategy",        "🦅 Trump Trades"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

def load(folder):
    path = os.path.join(BASE, folder, "data", "portfolio.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)

def current_equity(data):
    market = sum(
        p["shares"] * p.get("current_price", p["entry_price"])
        for p in data.get("open_positions", {}).values()
    )
    return data["cash"] + market

def equity_yesterday(data):
    for entry in reversed(data.get("equity_history", [])):
        if entry["date"] < TODAY:
            return entry["equity"]
    return data["initial_capital"]

def trades_closed_today(data):
    return [t for t in data.get("closed_trades", [])
            if t.get("exit_date", "")[:10] == TODAY]

def positions_opened_today(data):
    return [(t, pos) for t, pos in data.get("open_positions", {}).items()
            if pos.get("entry_date", "")[:10] == TODAY]

def win_rate(data):
    closed = data.get("closed_trades", [])
    if not closed:
        return None
    wins = sum(1 for t in closed if t["pnl"] > 0)
    return wins / len(closed)

# ── Report generator ──────────────────────────────────────────────────────────

def generate():
    lines = []
    lines.append(f"# 📊 Reporte Diario — {TODAY}")
    lines.append(f"\n> Generado: {datetime.utcnow().strftime('%d/%m/%Y %H:%M UTC')}\n")

    # ── Tabla resumen global ──────────────────────────────────────────────
    lines.append("## Resumen global\n")
    lines.append("| Estrategia | Equity | Retorno | Hoy | Posiciones | Win% |")
    lines.append("|---|---|---|---|---|---|")

    total_initial = total_equity = 0
    total_day_pnl = 0
    any_activity = False

    for folder, name in STRATEGIES:
        data = load(folder)
        if data is None:
            lines.append(f"| {name} | — | — | — | — | — |")
            continue

        initial  = data["initial_capital"]
        equity   = current_equity(data)
        ret      = (equity - initial) / initial
        eq_yd    = equity_yesterday(data)
        day_pnl  = equity - eq_yd
        wr       = win_rate(data)
        n_open   = len(data.get("open_positions", {}))
        closed_t = trades_closed_today(data)
        new_pos  = positions_opened_today(data)

        total_initial += initial
        total_equity  += equity
        total_day_pnl += day_pnl

        day_str = f"${day_pnl:+,.0f}" if abs(day_pnl) > 0.01 else "—"
        wr_str  = f"{wr:.0%}" if wr is not None else "—"
        act     = ""
        if closed_t:  act += f" {len(closed_t)}↩"
        if new_pos:   act += f" {len(new_pos)}↑"
        if act:
            any_activity = True

        lines.append(
            f"| {name} | ${equity:,.0f} | {ret:+.1%} | {day_str}{act} | {n_open}/3 | {wr_str} |"
        )

    total_ret = (total_equity - total_initial) / total_initial
    lines.append(f"| **TOTAL** | **${total_equity:,.0f}** | **{total_ret:+.1%}** | "
                 f"**${total_day_pnl:+,.0f}** | | |")

    lines.append("")

    # ── Detalle por estrategia ────────────────────────────────────────────
    lines.append("---\n")
    lines.append("## Detalle por estrategia\n")

    for folder, name in STRATEGIES:
        data = load(folder)
        if data is None:
            continue

        initial  = data["initial_capital"]
        equity   = current_equity(data)
        ret      = (equity - initial) / initial
        eq_yd    = equity_yesterday(data)
        day_pnl  = equity - eq_yd
        closed_t = trades_closed_today(data)
        new_pos  = positions_opened_today(data)
        open_pos = data.get("open_positions", {})
        closed_all = data.get("closed_trades", [])
        wr       = win_rate(data)

        lines.append(f"### {name}\n")
        lines.append(
            f"**Equity:** ${equity:,.0f} ({ret:+.1%} total)  "
            f"**Hoy:** ${day_pnl:+,.0f}  "
            f"**Trades totales:** {len(closed_all)}  "
            f"**Win rate:** {f'{wr:.0%}' if wr else '—'}"
        )

        # Posiciones abiertas hoy
        if new_pos:
            lines.append("\n**🟢 Nuevas posiciones abiertas hoy:**")
            for ticker, pos in new_pos:
                lines.append(
                    f"- **{ticker}** @ ${pos['entry_price']:.2f}  "
                    f"| ${pos['entry_value']:,.0f} invertido"
                )

        # Trades cerrados hoy
        if closed_t:
            lines.append("\n**Trades cerrados hoy:**")
            for t in closed_t:
                emoji = "🟢" if t["pnl"] > 0 else "🔴"
                lines.append(
                    f"- {emoji} **{t['ticker']}**  "
                    f"entrada ${t['entry_price']:.2f} → salida ${t['exit_price']:.2f}  "
                    f"| P&L: **${t['pnl']:+,.0f}** ({t['pnl_pct']:+.1%})  "
                    f"| {t.get('trading_days_held', '?')}d  "
                    f"| {t['exit_reason']}"
                )

        # Posiciones en curso
        if open_pos:
            lines.append("\n**Posiciones en curso:**")
            for ticker, pos in open_pos.items():
                curr    = pos.get("current_price", pos["entry_price"])
                pnl_pct = (curr - pos["entry_price"]) / pos["entry_price"]
                peak    = pos.get("peak_price", pos["entry_price"])
                desde_peak = (curr - peak) / peak if peak > 0 else 0
                days    = pos.get("trading_days_held", 0)
                emoji   = "📈" if pnl_pct >= 0 else "📉"
                lines.append(
                    f"- {emoji} **{ticker}** entrada ${pos['entry_price']:.2f}  "
                    f"actual ${curr:.2f} ({pnl_pct:+.1%})  "
                    f"| pico ${peak:.2f} (desde pico {desde_peak:+.1%})  "
                    f"| {days}d"
                )

        if not new_pos and not closed_t and not open_pos:
            lines.append("\n_Sin actividad — no hay posiciones abiertas ni trades hoy._")

        lines.append("")

    # ── Pie ───────────────────────────────────────────────────────────────
    lines.append("---")
    lines.append(f"\n*Reporte generado automáticamente por Paper Trading Bot · {TODAY}*")

    return "\n".join(lines)


def save(content):
    report_dir = os.path.join(BASE, "reports")
    os.makedirs(report_dir, exist_ok=True)
    path = os.path.join(report_dir, f"{TODAY}.md")
    with open(path, "w") as f:
        f.write(content)
    print(f"[report] Guardado en reports/{TODAY}.md")
    return path


def print_console(content):
    """Versión compacta para consola (sin markdown)."""
    print("\n" + "="*68)
    print(f"  REPORTE DIARIO — {TODAY}")
    print("="*68)

    for folder, name in STRATEGIES:
        data = load(folder)
        if data is None:
            continue
        initial  = data["initial_capital"]
        equity   = current_equity(data)
        ret      = (equity - initial) / initial
        eq_yd    = equity_yesterday(data)
        day_pnl  = equity - eq_yd
        n_open   = len(data.get("open_positions", {}))
        closed_t = trades_closed_today(data)
        new_pos  = positions_opened_today(data)
        wr       = win_rate(data)

        activity = []
        if new_pos:   activity.append(f"{len(new_pos)} abierta(s)")
        if closed_t:  activity.append(f"{len(closed_t)} cerrada(s)")
        act_str = " | ".join(activity) if activity else "sin trades hoy"

        print(f"\n  {name}")
        print(f"    Equity ${equity:,.0f} ({ret:+.1%}) | Hoy ${day_pnl:+,.0f} | Posiciones {n_open}/3")
        print(f"    Win rate: {f'{wr:.0%}' if wr else '—'} | Actividad: {act_str}")

        for ticker, pos in data.get("open_positions", {}).items():
            curr = pos.get("current_price", pos["entry_price"])
            pnl  = (curr - pos["entry_price"]) / pos["entry_price"]
            print(f"    → {ticker} @ ${pos['entry_price']:.2f} | actual ${curr:.2f} ({pnl:+.1%}) | {pos.get('trading_days_held',0)}d")

        for t in closed_t:
            emoji = "🟢" if t["pnl"] > 0 else "🔴"
            print(f"    {emoji} CERRÓ {t['ticker']} | P&L ${t['pnl']:+,.0f} ({t['pnl_pct']:+.1%}) | {t['exit_reason']}")

    # Totales
    ti = te = 0
    for folder, _ in STRATEGIES:
        data = load(folder)
        if data:
            ti += data["initial_capital"]
            te += current_equity(data)
    print(f"\n{'─'*68}")
    print(f"  TOTAL: ${te:,.0f} / ${ti:,.0f} ({(te-ti)/ti:+.1%})")
    print("="*68 + "\n")


if __name__ == "__main__":
    content = generate()
    save(content)
    print_console(content)
