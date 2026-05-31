"""
Señal para Polymarket — sin lookahead bias.

Estrategia: momentum de probabilidad.
  - Obtiene los mercados más activos (mayor volumen de las últimas 24h).
  - Selecciona mercados donde la probabilidad del outcome favorito lleva
    varios días subiendo (momentum de probabilidad).
  - Entra comprando YES del outcome con momentum positivo.
  - Precio de entrada = probabilidad actual (0.0–1.0), equivale a pagar
    $X por un contrato que vale $1 si resuelve YES.

Sin lookahead bias:
  - La señal usa precios históricos ya confirmados (no precio del día actual
    como señal de entrada: la señal es el momentum de días anteriores).
  - El precio de ejecución es el precio actual de mercado.
"""
from __future__ import annotations

import time
import requests
from datetime import datetime, timedelta

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE  = "https://clob.polymarket.com"
HEADERS    = {"Accept": "application/json", "User-Agent": "paper-trading-bot/1.0"}

# Mínimos para filtrar mercados poco líquidos
MIN_VOLUME_24H = 5_000    # $5k volumen en 24h
MIN_LIQUIDITY  = 2_000    # $2k liquidez


def get_active_markets(limit: int = 50) -> list[dict]:
    """Obtiene mercados activos ordenados por volumen."""
    try:
        r = requests.get(
            f"{GAMMA_BASE}/markets",
            params={
                "active"  : "true",
                "closed"  : "false",
                "limit"   : limit,
                "order"   : "volume24hr",
                "ascending": "false",
            },
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        # La API puede devolver list o dict con "markets"
        if isinstance(data, list):
            return data
        return data.get("markets", data.get("data", []))
    except Exception as e:
        print(f"[strategy] Error obteniendo mercados: {e}")
        return []


def get_market_prices(condition_id: str) -> list[dict]:
    """Obtiene historial de precios de un mercado desde el CLOB."""
    try:
        r = requests.get(
            f"{CLOB_BASE}/prices-history",
            params={
                "market"     : condition_id,
                "interval"   : "1d",
                "fidelity"   : 7,
            },
            headers=HEADERS,
            timeout=10,
        )
        if r.status_code == 200:
            return r.json().get("history", [])
    except Exception:
        pass
    return []


def compute_momentum_signals(top_n: int = 5) -> tuple[list[dict], list[dict]]:
    """
    Retorna (seleccionados, todos) donde cada elemento tiene:
      condition_id, question, outcome, price, price_3d_ago, momentum, volume_24h

    Selecciona los top_n mercados con mayor momentum de probabilidad positivo.
    """
    markets = get_active_markets(limit=100)
    print(f"[strategy] {len(markets)} mercados activos obtenidos")

    candidates = []

    for m in markets:
        try:
            # Filtrar por liquidez y volumen
            vol = float(m.get("volume24hr") or m.get("volume") or 0)
            liq = float(m.get("liquidity") or 0)

            if vol < MIN_VOLUME_24H:
                continue
            if liq < MIN_LIQUIDITY:
                continue

            # Mercado no resuelto
            if m.get("closed") or m.get("resolved"):
                continue

            # Obtener outcomes
            outcomes       = m.get("outcomes", "[]")
            outcome_prices = m.get("outcomePrices", "[]")

            if isinstance(outcomes, str):
                import json
                try:
                    outcomes       = json.loads(outcomes)
                    outcome_prices = json.loads(outcome_prices)
                except Exception:
                    continue

            if not outcomes or not outcome_prices:
                continue

            # Buscar el outcome YES (o el que tenga mayor precio)
            yes_idx   = None
            yes_price = 0.0
            for i, (out, pr) in enumerate(zip(outcomes, outcome_prices)):
                p = float(pr)
                if out.lower() == "yes" or p > yes_price:
                    yes_idx   = i
                    yes_price = p

            if yes_idx is None or not (0.05 <= yes_price <= 0.95):
                continue

            yes_outcome = outcomes[yes_idx]

            # Obtener historial de precios para calcular momentum
            cond_id  = m.get("conditionId") or m.get("id", "")
            price_3d = yes_price  # fallback: sin historial = momentum 0

            history = get_market_prices(cond_id)
            if len(history) >= 4:
                # Precio de hace 3 días (sin lookahead)
                history_sorted = sorted(history, key=lambda x: x.get("t", 0))
                price_3d = float(history_sorted[-4].get("p", yes_price))

            momentum = yes_price - price_3d

            candidates.append({
                "condition_id" : cond_id,
                "question"     : m.get("question", m.get("title", "Unknown"))[:80],
                "outcome"      : yes_outcome,
                "price"        : yes_price,
                "price_3d_ago" : price_3d,
                "momentum"     : momentum,
                "volume_24h"   : vol,
                "liquidity"    : liq,
                "end_date"     : m.get("endDate", m.get("endDateIso", "")),
            })

            time.sleep(0.2)

        except Exception as e:
            print(f"[strategy] Error procesando mercado: {e}")
            continue

    # Ordenar por momentum descendente
    candidates.sort(key=lambda x: x["momentum"], reverse=True)

    # Solo entrar en mercados con momentum positivo
    positivos = [c for c in candidates if c["momentum"] > 0]
    selected  = positivos[:top_n]

    if selected:
        print(f"[strategy] Top {len(selected)} mercados seleccionados:")
        for c in selected:
            print(
                f"  [{c['outcome']:<4}] {c['question'][:50]:<50} "
                f"p={c['price']:.2f} mom={c['momentum']:+.3f}"
            )
    else:
        print("[strategy] Sin mercados con momentum positivo")

    return selected, candidates
