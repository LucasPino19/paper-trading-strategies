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
tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8, tab9, tab10, tab11, tab12, tab13 = st.tabs([
    "🎮 GameStop Squeeze",
    "🦅 Trump Trades",
    "📐 FVG + VWAP",
    "🧱 ICT Order Blocks",
    "🚀 Gap & Go",
    "📊 ORB + Breakout",
    "📈 Breakout 50d",
    "⚡ Momentum 10d",
    "🎯 BB Bounce",
    "↩️ Pullback EMA50",
    "🏆 Momentum SP500",
    "🐸 Memecoins",
    "🔮 Polymarket",
])

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
    with st.expander("¿Cómo funciona?"):
        st.markdown("Busca **mensualmente** acciones con short interest >40%, float <100M y volumen >2x promedio. Entra cuando el squeeze parece inminente.")

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
    with st.expander("¿Cómo funciona?"):
        st.markdown("Lee Google News **cada hora** buscando declaraciones de Trump sobre acciones. Positivo → compra. Negativo sobre posición abierta → vende.")

with tab3:
    fvg = load_portfolio("fvg-strategy")
    s_fvg = summary(fvg)
    render_kpis(s_fvg)
    render_equity_curve(fvg, s_fvg)
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Posiciones abiertas")
        render_open_positions(fvg)
    with col_b:
        st.subheader("Trades cerrados")
        render_trade_history(fvg)
    with st.expander("¿Cómo funciona?"):
        st.markdown("Detecta **Fair Value Gaps** en velas de 1h sobre las 20 acciones más líquidas del S&P 500. Entra solo cuando FVG + VWAP + Breakout coinciden. Stop 1.5×FVG, target 2×FVG.")

with tab4:
    ict = load_portfolio("ict-strategy")
    s_ict = summary(ict)
    render_kpis(s_ict)
    render_equity_curve(ict, s_ict)
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Posiciones abiertas")
        render_open_positions(ict)
    with col_b:
        st.subheader("Trades cerrados")
        render_trade_history(ict)
    with st.expander("¿Cómo funciona?"):
        st.markdown("Detecta **Order Blocks ICT** en velas de 1h. Entra cuando el precio retoca un OB con VWAP y EMA(20) alineados. Stop 1.5×OB, target 3×OB.")

with tab5:
    gap = load_portfolio("gap-strategy")
    s_gap = summary(gap)
    render_kpis(s_gap)
    render_equity_curve(gap, s_gap)
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Posiciones abiertas")
        render_open_positions(gap)
    with col_b:
        st.subheader("Trades cerrados")
        render_trade_history(gap)
    with st.expander("¿Cómo funciona?"):
        st.markdown("Detecta **gaps alcistas >1%** en apertura. Entra a las 10:30 ET si el precio mantiene el gap y el volumen es 1.5× la media. Stop -8%, target +30%, trail desde +12%.")

with tab6:
    orb = load_portfolio("orb-breakout-strategy")
    s_orb = summary(orb)
    render_kpis(s_orb)
    render_equity_curve(orb, s_orb)
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Posiciones abiertas")
        render_open_positions(orb)
    with col_b:
        st.subheader("Trades cerrados")
        render_trade_history(orb)
    with st.expander("¿Cómo funciona?"):
        st.markdown("Combina **Opening Range Breakout** (supera máximo de la primera vela de 1h) con rotura del **máximo de 20 días**, volumen elevado y precio sobre EMA20. Stop -7%, target +20%.")

with tab7:
    b50d = load_portfolio("breakout50d-strategy")
    s_b50d = summary(b50d)
    render_kpis(s_b50d)
    render_equity_curve(b50d, s_b50d)
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Posiciones abiertas")
        render_open_positions(b50d)
    with col_b:
        st.subheader("Trades cerrados")
        render_trade_history(b50d)
    with st.expander("¿Cómo funciona?"):
        st.markdown("Opera en **datos diarios**. Entra en el primer cierre que supera el máximo de los últimos **50 días**. Sin hard target — usa trailing stop puro (trail 8% desde pico). Backtest: +89.8% total en 4.7 años.")

with tab8:
    mom = load_portfolio("momentum-strategy")
    s_mom = summary(mom)
    render_kpis(s_mom)
    render_equity_curve(mom, s_mom)
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Posiciones abiertas")
        render_open_positions(mom)
    with col_b:
        st.subheader("Trades cerrados")
        render_trade_history(mom)
    with st.expander("¿Cómo funciona?"):
        st.markdown("Detecta **cruce de momentum positivo**: retorno de 10 días (70 barras de 1h) que cruza por encima del 4% por primera vez, con precio sobre EMA50. Stop -6%, target +12%. 77% meses positivos en backtest.")

with tab9:
    bb = load_portfolio("bb-bounce-strategy")
    s_bb = summary(bb)
    render_kpis(s_bb)
    render_equity_curve(bb, s_bb)
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Posiciones abiertas")
        render_open_positions(bb)
    with col_b:
        st.subheader("Trades cerrados")
        render_trade_history(bb)
    with st.expander("¿Cómo funciona?"):
        st.markdown("**BB Lower Bounce**: compra cuando el precio toca la Banda de Bollinger inferior y rebota al día siguiente, con RSI < 45 y precio sobre EMA200 (tendencia alcista). Stop -7%, target +15%. Backtest: **62% win rate, PF 2.29, DD -12%**.")

with tab10:
    pull = load_portfolio("pullback-strategy")
    s_pull = summary(pull)
    render_kpis(s_pull)
    render_equity_curve(pull, s_pull)
    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("Posiciones abiertas")
        render_open_positions(pull)
    with col_b:
        st.subheader("Trades cerrados")
        render_trade_history(pull)
    with st.expander("¿Cómo funciona?"):
        st.markdown("**Pullback EMA50 + ADX**: compra cuando el precio retrocede a tocar la EMA50 en tendencia alcista (precio > EMA200), rebota, y el ADX > 20 confirma que el mercado está en tendencia (no lateral). Stop -6%, trailing stop puro. Backtest: **+21.5% anual, DD -33%**.")

with tab11:
    sp500mom = load_portfolio("momentum-sp500-strategy")
    s_sp500  = summary(sp500mom)

    # KPIs adaptados para basket (más de 3 posiciones)
    n_pos = len(sp500mom.get("open_positions", {}))
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Equity", f"${s_sp500['total_equity']:,.0f}", delta=f"{s_sp500['total_return']:+.1%}")
    c2.metric("Cash", f"${s_sp500['cash']:,.0f}")
    c3.metric("P&L realizado", f"${s_sp500['realized_pnl']:+,.0f}")
    c4.metric("Posiciones", f"{n_pos} (~22 target)")
    c5.metric(
        "Win Rate",
        f"{s_sp500['win_rate']:.0%}" if s_sp500["closed"] else "—",
        delta=f"{s_sp500['wins']}W / {s_sp500['losses']}L" if s_sp500["closed"] else None,
    )

    render_equity_curve(sp500mom, s_sp500)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader(f"Posiciones actuales ({n_pos})")
        render_open_positions(sp500mom)
    with col_b:
        st.subheader("Trades cerrados (rebalanceos)")
        render_trade_history(sp500mom)

    with st.expander("¿Cómo funciona?"):
        st.markdown(
            "**Momentum SP500 — factor cuantitativo.** "
            "Cada mes selecciona el **top 5% del S&P 500** (≈22 acciones) "
            "por retorno de los últimos 12 meses, saltando el último mes para evitar "
            "reversión de corto plazo. Peso igual entre todas las posiciones. "
            "Sin stop loss individual — el filtro es el propio ranking mensual. "
            "**Backtest honesto (2011–2026):** CAGR ~18% vs SPY ~14%, "
            "alpha +4% anual out-of-sample. ⚠️ Survivorship bias presente: "
            "alpha real estimado +1-2% sobre SPY."
        )

with tab12:
    meme = load_portfolio("memecoin-strategy")
    s_meme = summary(meme)

    n_meme = len(meme.get("open_positions", {}))
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Equity", f"${s_meme['total_equity']:,.0f}", delta=f"{s_meme['total_return']:+.1%}")
    c2.metric("Cash", f"${s_meme['cash']:,.0f}")
    c3.metric("P&L realizado", f"${s_meme['realized_pnl']:+,.0f}")
    c4.metric("Posiciones", f"{n_meme} (5 target)")
    c5.metric(
        "Win Rate",
        f"{s_meme['win_rate']:.0%}" if s_meme["closed"] else "—",
        delta=f"{s_meme['wins']}W / {s_meme['losses']}L" if s_meme["closed"] else None,
    )

    render_equity_curve(meme, s_meme)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader(f"Posiciones actuales ({n_meme})")
        render_open_positions(meme)
    with col_b:
        st.subheader("Trades cerrados")
        render_trade_history(meme)

    with st.expander("¿Cómo funciona?"):
        st.markdown(
            "**Memecoin Momentum — rotación semanal.** "
            "Cada lunes selecciona las **top 5 memecoins** (de DOGE, SHIB, PEPE, WIF, BONK, etc.) "
            "con mayor retorno de los últimos 7 días, filtrando por market cap >$50M y volumen >$1M. "
            "Excluye pumps extremos (>1000% en 7d = probable manipulación). "
            "Peso igual entre las 5 posiciones. Sin stop loss individual — "
            "la rotación semanal actúa como filtro. Datos: CoinGecko API (gratis)."
        )

with tab13:
    poly = load_portfolio("polymarket-strategy")
    s_poly = summary(poly)

    n_poly = len(poly.get("open_positions", {}))
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Equity", f"${s_poly['total_equity']:,.0f}", delta=f"{s_poly['total_return']:+.1%}")
    c2.metric("Cash", f"${s_poly['cash']:,.0f}")
    c3.metric("P&L realizado", f"${s_poly['realized_pnl']:+,.0f}")
    c4.metric("Posiciones", f"{n_poly} (5 target)")
    c5.metric(
        "Win Rate",
        f"{s_poly['win_rate']:.0%}" if s_poly["closed"] else "—",
        delta=f"{s_poly['wins']}W / {s_poly['losses']}L" if s_poly["closed"] else None,
    )

    render_equity_curve(poly, s_poly)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader(f"Posiciones actuales ({n_poly})")
        if poly.get("open_positions"):
            rows = []
            for cid, pos in poly["open_positions"].items():
                current = pos.get("current_price", pos["entry_price"])
                pnl_pct = (current - pos["entry_price"]) / pos["entry_price"] if pos["entry_price"] > 0 else 0
                rows.append({
                    "Mercado"  : pos.get("ticker", cid)[:40],
                    "Outcome"  : pos.get("outcome", "YES"),
                    "Entrada"  : f"{pos['entry_price']:.3f}",
                    "Actual"   : f"{current:.3f}",
                    "P&L %"    : f"{pnl_pct:+.1%}",
                    "P&L $"    : f"${pos['shares']*(current-pos['entry_price']):+,.0f}",
                    "Días"     : pos.get("trading_days_held", 0),
                })
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        else:
            st.info("No hay posiciones abiertas.")
    with col_b:
        st.subheader("Trades cerrados")
        render_trade_history(poly)

    with st.expander("¿Cómo funciona?"):
        st.markdown(
            "**Polymarket Momentum — mercados de predicción.** "
            "Selecciona los 5 mercados más activos (>$5k volumen 24h) donde la probabilidad "
            "del outcome favorito lleva subiendo 3 días seguidos (momentum de probabilidad). "
            "Compra contratos YES a precio actual (= probabilidad implícita $0–1). "
            "**Take profit:** +20 puntos de probabilidad. "
            "**Stop loss:** −15 puntos de probabilidad. "
            "Datos: Polymarket Gamma API (gratis)."
        )
