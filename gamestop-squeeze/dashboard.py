"""Dashboard Streamlit para seguimiento del paper trading GameStop squeeze."""
from __future__ import annotations

import os
import sys

# Asegura que los módulos del bot sean importables desde Streamlit Community Cloud
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from paper_trader import PaperTrader
from strategy import ENTRY, EXIT

st.set_page_config(
    page_title="GameStop Squeeze — Paper Trading",
    page_icon="📈",
    layout="wide",
)

# ── Auto-refresh cada 5 minutos durante mercado abierto ──────────────────────
st.markdown(
    "<meta http-equiv='refresh' content='300'>",
    unsafe_allow_html=True,
)

st.title("📈 GameStop Squeeze — Paper Trading")
st.caption(f"Actualizado: {datetime.now().strftime('%d/%m/%Y %H:%M')}  |  Capital inicial: $10,000")

trader = PaperTrader()
summary = trader.get_summary()

# ── KPIs principales ─────────────────────────────────────────────────────────
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Equity total", f"${summary['total_equity']:,.0f}",
          delta=f"{summary['total_return_pct']:+.1%}")
c2.metric("Cash disponible", f"${summary['cash']:,.0f}")
c3.metric("P&L realizado", f"${summary['realized_pnl']:+,.0f}")
c4.metric("Posiciones abiertas", f"{summary['open_positions']} / 3")
c5.metric(
    "Win Rate",
    f"{summary['win_rate']:.0%}" if summary["closed_trades"] else "—",
    delta=f"{summary['wins']}W / {summary['losses']}L" if summary["closed_trades"] else None,
)

st.divider()

# ── Equity curve ─────────────────────────────────────────────────────────────
history = trader._state.get("equity_history", [])
if len(history) > 1:
    st.subheader("Curva de equity")
    df_eq = pd.DataFrame(history)
    df_eq["date"] = pd.to_datetime(df_eq["date"])
    initial = summary["initial_capital"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df_eq["date"], y=df_eq["equity"],
        fill="tozeroy",
        fillcolor="rgba(34,197,94,0.1)",
        line=dict(color="#22c55e", width=2),
        name="Equity",
        hovertemplate="$%{y:,.0f}<extra></extra>",
    ))
    fig.add_hline(
        y=initial, line_dash="dash", line_color="gray",
        annotation_text=f"Capital inicial ${initial:,.0f}",
        annotation_position="bottom right",
    )
    fig.update_layout(height=280, margin=dict(l=0, r=0, t=10, b=0),
                      yaxis_tickprefix="$", yaxis_tickformat=",")
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("La curva de equity aparecerá después del primer día de operaciones.")

# ── Posiciones abiertas ───────────────────────────────────────────────────────
st.subheader("Posiciones abiertas")
if trader.open_positions:
    rows = []
    for ticker, pos in trader.open_positions.items():
        current = pos.get("current_price", pos["entry_price"])
        pnl_pct = (current - pos["entry_price"]) / pos["entry_price"]
        pnl_usd = pos["shares"] * (current - pos["entry_price"])
        rows.append({
            "Ticker": ticker,
            "Entrada": f"${pos['entry_price']:.2f}",
            "Precio actual": f"${current:.2f}",
            "P&L %": f"{pnl_pct:+.1%}",
            "P&L $": f"${pnl_usd:+,.0f}",
            "SPS": f"{pos['sps_score']:.0f}/100",
            "Short %": f"{pos.get('short_float_pct', 0):.0f}%",
            "Float": f"{pos.get('float_shares_m', 0):.0f}M",
            "DTC": f"{pos.get('dtc', 0):.1f}d",
            "Días": pos.get("trading_days_held", 0),
            "Pico": f"${pos.get('peak_price', pos['entry_price']):.2f}",
            "Fecha entrada": pos["entry_date"][:10],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Gauge de riesgo de cada posición
    with st.expander("Ver condiciones de salida activas"):
        st.markdown(f"""
        | Condición | Threshold |
        |-----------|-----------|
        | Stop loss | -{abs(EXIT['stop_loss']):.0%} desde entrada |
        | Target duro | +{EXIT['hard_target']:.0%} |
        | Trailing stop | -{EXIT['trailing_pct']:.0%} desde pico (activa a +{EXIT['trailing_trigger']:.0%}) |
        | Stop de tiempo | {EXIT['time_stop_days']} días sin +{EXIT['time_stop_min_gain']:.0%} |
        | Agotamiento vol. | Volumen < {EXIT['vol_exhaustion_ratio']}x avg tras spike |
        """)
else:
    st.info(
        "No hay posiciones abiertas. "
        "Ejecutá `python run.py --scan` para buscar candidatos."
    )

# ── Historial de trades ───────────────────────────────────────────────────────
st.subheader("Historial de trades cerrados")
closed = trader._state.get("closed_trades", [])
if closed:
    rows = []
    for t in reversed(closed):
        rows.append({
            "Ticker": t["ticker"],
            "Entrada": f"${t['entry_price']:.2f}",
            "Salida": f"${t['exit_price']:.2f}",
            "P&L %": f"{t['pnl_pct']:+.1%}",
            "P&L $": f"${t['pnl']:+,.0f}",
            "SPS": f"{t.get('sps_score', 0):.0f}/100",
            "Días": t.get("trading_days_held", "—"),
            "Razón de salida": t["exit_reason"],
            "Fecha entrada": t["entry_date"][:10],
            "Fecha salida": t["exit_date"][:10],
        })
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # Distribución de P&L
    if len(closed) >= 3:
        col_a, col_b = st.columns(2)
        with col_a:
            st.caption("Distribución de resultados")
            pnl_vals = [t["pnl_pct"] * 100 for t in closed]
            fig2 = px.histogram(
                x=pnl_vals, nbins=15,
                labels={"x": "P&L %"},
                color_discrete_sequence=["#6366f1"],
            )
            fig2.add_vline(x=0, line_dash="dash", line_color="red",
                           annotation_text="break-even")
            fig2.update_layout(height=220, margin=dict(l=0, r=0, t=20, b=0),
                               showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)
        with col_b:
            st.caption("P&L acumulado por trade")
            df_pnl = pd.DataFrame([
                {"trade": i + 1, "pnl_acum": sum(t["pnl"] for t in closed[: i + 1])}
                for i, _ in enumerate(closed)
            ])
            fig3 = px.bar(df_pnl, x="trade", y="pnl_acum",
                          color_discrete_sequence=["#22c55e"],
                          labels={"trade": "Trade #", "pnl_acum": "P&L acum. $"})
            fig3.add_hline(y=0, line_color="gray")
            fig3.update_layout(height=220, margin=dict(l=0, r=0, t=20, b=0))
            st.plotly_chart(fig3, use_container_width=True)
else:
    st.info("Todavía no hay trades cerrados.")

# ── Info de la estrategia ─────────────────────────────────────────────────────
st.divider()
with st.expander("Cómo funciona esta estrategia"):
    st.markdown(f"""
    **GameStop Squeeze Detector** busca mensualmente acciones que reúnen las condiciones
    que convirtieron a GME en el squeeze más famoso de la historia:

    | Filtro de entrada | Valor |
    |-------------------|-------|
    | Short Interest (% float) | > {ENTRY['min_short_float_pct']:.0f}% |
    | Float de acciones | < {ENTRY['max_float_m']:.0f}M shares |
    | Days to Cover (DTC) | > {ENTRY['min_dtc']:.0f} días |
    | Volumen vs. promedio | > {ENTRY['min_volume_ratio']:.0f}x |

    El **SPS (Squeeze Potential Score)** pondera estas variables en un score 0–100.
    Se abren hasta **3 posiciones simultáneas**, cada una usando el **30% del capital disponible**.

    Las salidas se manejan automáticamente por 5 condiciones priorizadas:
    stop loss, target duro, trailing stop, stop de tiempo y agotamiento de volumen.
    """)
