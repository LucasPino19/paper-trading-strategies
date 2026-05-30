"""Dashboard unificado — todas las estrategias de paper trading."""
from __future__ import annotations

import json
import os
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(
    page_title="Paper Trading Dashboard",
    page_icon="📊",
    layout="wide",
)

_ROOT = os.path.dirname(os.path.abspath(__file__))


def load_portfolio(strategy_folder: str) -> dict:
    path = os.path.join(_ROOT, strategy_folder, "data", "portfolio.json")
    if not os.path.exists(path):
        return {
            "initial_capital": 10000.0, "cash": 10000.0,
            "open_positions": {}, "closed_trades": [],
            "equity_history": [],
        }
    with open(path) as f:
        return json.load(f)


def summary(data: dict) -> dict:
    market_val = sum(
        p["shares"] * p.get("current_price", p["entry_price"])
        for p in data["open_positions"].values()
    )
    invested = sum(p["entry_value"] for p in data["open_positions"].values())
    closed = data["closed_trades"]
    realized = sum(t["pnl"] for t in closed)
    wins = sum(1 for t in closed if t["pnl"] > 0)
    total_eq = data["cash"] + market_val
    init = data["initial_capital"]
    return {
        "total_equity": total_eq,
        "total_return": (total_eq - init) / init,
        "cash": data["cash"],
        "realized_pnl": realized,
        "unrealized_pnl": market_val - invested,
        "open": len(data["open_positions"]),
        "closed": len(closed),
        "wins": wins,
        "losses": len(closed) - wins,
        "win_rate": wins / len(closed) if closed else 0.0,
        "initial_capital": init,
    }


def render_kpis(s: dict) -> None:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Equity", f"${s['total_equity']:,.0f}", delta=f"{s['total_return']:+.1%}")
    c2.metric("Cash", f"${s['cash']:,.0f}")
    c3.metric("P&L realizado", f"${s['realized_pnl']:+,.0f}")
    c4.metric("Posiciones", f"{s['open']} / 3")
    c5.metric(
        "Win Rate",
        f"{s['win_rate']:.0%}" if s["closed"] else "—",
        delta=f"{s['wins']}W / {s['losses']}L" if s["closed"] else None,
    )


def render_equity_curve(data: dict, s: dict) -> None:
    history = data.get("equity_history", [])
    if len(history) < 2:
        st.info("La curva de equity aparecerá después del primer día de operaciones.")
        return
    df = pd.DataFrame(history)
    df["date"] = pd.to_datetime(df["date"])
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["equity"],
        fill="tozeroy", fillcolor="rgba(99,102,241,0.1)",
        line=dict(color="#6366f1", width=2),
        hovertemplate="$%{y:,.0f}<extra></extra>",
    ))
    fig.add_hline(
        y=s["initial_capital"], line_dash="dash", line_color="gray",
        annotation_text=f"Capital inicial ${s['initial_capital']:,.0f}",
        annotation_position="bottom right",
    )
    fig.update_layout(height=260, margin=dict(l=0, r=0, t=10, b=0),
                      yaxis_tickprefix="$", yaxis_tickformat=",")
    st.plotly_chart(fig, use_container_width=True)


def render_open_positions(data: dict) -> None:
    if not data["open_positions"]:
        st.info("No hay posiciones abiertas.")
        return
    rows = []
    for ticker, pos in data["open_positions"].items():
        current = pos.get("current_price", pos["entry_price"])
        pnl_pct = (current - pos["entry_price"]) / pos["entry_price"]
        rows.append({
            "Ticker": ticker,
            "Entrada": f"${pos['entry_price']:.2f}",
            "Actual": f"${current:.2f}",
            "P&L %": f"{pnl_pct:+.1%}",
            "P&L $": f"${pos['shares']*(current-pos['entry_price']):+,.0f}",
            "Días": pos.get("trading_days_held", 0),
            "Fecha": pos["entry_date"][:10],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_trade_history(data: dict) -> None:
    closed = data["closed_trades"]
    if not closed:
        st.info("Todavía no hay trades cerrados.")
        return
    rows = [{
        "Ticker": t["ticker"],
        "Entrada": f"${t['entry_price']:.2f}",
        "Salida": f"${t['exit_price']:.2f}",
        "P&L %": f"{t['pnl_pct']:+.1%}",
        "P&L $": f"${t['pnl']:+,.0f}",
        "Días": t.get("trading_days_held", "—"),
        "Razón": t["exit_reason"][:45],
        "Fecha entrada": t["entry_date"][:10],
        "Fecha salida": t["exit_date"][:10],
    } for t in reversed(closed)]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


# ── Header ────────────────────────────────────────────────────────────────────
st.title("📊 Paper Trading Dashboard")
st.caption(f"Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}  |  $10,000 por estrategia")
st.divider()

# ── Tabs por estrategia ───────────────────────────────────────────────────────
tab1, tab2 = st.tabs(["🎮 GameStop Squeeze", "🦅 Trump Trades"])

with tab1:
    gme = load_portfolio("gamestop-squeeze")
    s_gme = summary(gme)
    render_kpis(s_gme)
    render_equity_curve(gme, s_gme)
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Posiciones abiertas")
        render_open_positions(gme)
    with col_b:
        st.subheader("Trades cerrados")
        render_trade_history(gme)
    with st.expander("¿Cómo funciona esta estrategia?"):
        st.markdown("""
        Busca **mensualmente** acciones con short interest >40%, float <100M shares y
        volumen >2x promedio — las mismas condiciones que tenía GameStop en enero 2021.
        Entra cuando el squeeze parece inminente y sale por stop loss, target, trailing
        stop, tiempo o agotamiento de volumen.
        """)

with tab2:
    trump = load_portfolio("trump-strategy")
    s_trump = summary(trump)
    render_kpis(s_trump)
    render_equity_curve(trump, s_trump)
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Posiciones abiertas")
        render_open_positions(trump)
    with col_b:
        st.subheader("Trades cerrados")
        render_trade_history(trump)
    with st.expander("¿Cómo funciona esta estrategia?"):
        st.markdown("""
        Lee noticias de Trump **cada hora** (Google News RSS). Si menciona una empresa
        con tono positivo → compra. Si la menciona negativamente y está en portfolio → vende.
        Stop loss -8%, target +50%, trailing stop +15%, y tiempo máximo 5 días
        (las noticias de Trump duran poco).
        """)
