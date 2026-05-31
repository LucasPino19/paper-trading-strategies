"""
Polymarket Soccer — Favorite-Longshot Bias.

Fundamento empírico:
  En todos los mercados de apuestas existe el "favorite-longshot bias":
  los participantes sobrevaloran los underdogs (probabilidades bajas) y
  subvaloran a los favoritos. Apostar sistemáticamente en favoritos con
  60–80% de probabilidad tiene EV positivo documentado en la literatura
  de mercados de predicción (Rothschild 2009, Ottaviani & Sorensen 2010).

  El rango 60–80% es crítico:
    - <60% = demasiado equilibrado, sin ventaja clara
    - >80% = el mercado ya descontó casi todo, la ganancia potencial es pequeña
              y hay riesgo de sorpresa que destruye el bankroll

Sin lookahead bias:
  - Solo usamos el precio actual del mercado (ya publicado).
  - El precio de entrada es el precio actual de Polymarket.
"""
from __future__ import annotations

import json
import requests
import time

GAMMA_BASE = "https://gamma-api.polymarket.com"
HEADERS    = {"Accept": "application/json", "User-Agent": "paper-trading-bot/1.0"}

SOCCER_KEYWORDS = [
    "soccer", "football", "premier league", "champions league", "la liga",
    "bundesliga", "serie a", "ligue 1", "eredivisie", "copa", "euro",
    "world cup", "uefa", "fifa", "el clasico", "derby", "fa cup",
    "league cup", "carabao", "mls", "libertadores", "sudamericana",
    "win the match", "beat", "vs", "v ", "score", "goal",
]

MIN_VOL_24H = 5_000   # $5k — mercados con liquidez real
MIN_PROB    = 0.60    # favorito mínimo 60%
MAX_PROB    = 0.80    # favorito máximo 80%


def get_soccer_markets(limit: int = 200) -> list[dict]:
    """Obtiene mercados activos de Polymarket relacionados con fútbol."""
    try:
        r = requests.get(
            f"{GAMMA_BASE}/markets",
            params={"active": "true", "closed": "false", "limit": limit,
                    "order": "volume24hr", "ascending": "false"},
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        markets = data if isinstance(data, list) else data.get("markets", data.get("data", []))
    except Exception as e:
        print(f"[strategy] Error obteniendo mercados: {e}")
        return []

    soccer = []
    for m in markets:
        q = (m.get("question", "") + " " + m.get("title", "") +
             " " + m.get("category", "")).lower()
        if any(kw in q for kw in SOCCER_KEYWORDS):
            soccer.append(m)

    print(f"[strategy] {len(soccer)} mercados de fútbol encontrados de {len(markets)} totales")
    return soccer


def _parse_outcomes(m: dict) -> list[tuple[str, float]]:
    """Retorna lista de (outcome_name, probability) ordenados por probabilidad desc."""
    outcomes = m.get("outcomes", "[]")
    prices   = m.get("outcomePrices", "[]")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
            prices   = json.loads(prices)
        except Exception:
            return []
    pairs = []
    for out, pr in zip(outcomes, prices):
        try:
            p = float(pr)
            if 0.01 < p < 0.99:
                pairs.append((out, p))
        except (ValueError, TypeError):
            pass
    return sorted(pairs, key=lambda x: x[1], reverse=True)


def find_favorite_signals(
    top_n    : int   = 5,
    min_prob : float = MIN_PROB,
    max_prob : float = MAX_PROB,
) -> list[dict]:
    """
    Retorna los top_n mercados de fútbol donde el favorito tiene
    probabilidad en [min_prob, max_prob] y hay suficiente volumen.
    """
    markets = get_soccer_markets()
    candidates = []

    for m in markets:
        try:
            vol = float(m.get("volume24hr") or m.get("volume") or 0)
            if vol < MIN_VOL_24H:
                continue
            if m.get("closed") or m.get("resolved"):
                continue

            pairs = _parse_outcomes(m)
            if not pairs:
                continue

            fav_outcome, fav_prob = pairs[0]   # el de mayor probabilidad

            if not (min_prob <= fav_prob <= max_prob):
                continue

            cond_id  = m.get("conditionId") or m.get("id", "")
            question = m.get("question", m.get("title", ""))[:80]

            candidates.append({
                "condition_id" : cond_id,
                "question"     : question,
                "direction"    : "YES",
                "outcome"      : fav_outcome,
                "price"        : fav_prob,
                "volume_24h"   : vol,
                "end_date"     : m.get("endDate", ""),
            })
        except Exception:
            continue

    # Ordenar por volumen (mayor liquidez primero = mejor ejecución)
    candidates.sort(key=lambda x: x["volume_24h"], reverse=True)
    selected = candidates[:top_n]

    if selected:
        print(f"\n[strategy] Top {len(selected)} favoritos seleccionados:")
        for c in selected:
            print(f"  [{c['outcome']:<12}] p={c['price']:.2f}  vol=${c['volume_24h']:,.0f}  — {c['question'][:55]}")
    else:
        print("[strategy] Sin favoritos en rango 60–80% hoy")

    return selected
