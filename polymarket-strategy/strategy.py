"""
Polymarket — Fade de overreaction con confirmación de noticias.

Estrategia:
  Los mercados de predicción sobreajustan a noticias recientes: cuando una
  probabilidad se mueve >15 puntos en 24h, tiende a corregir parcialmente
  en los días siguientes (anchoring + recency bias de participantes retail).

  Señal de entrada (requiere AMBAS condiciones):
    1. El mercado se movió >15pp en las últimas 24h (detectado comparando
       el precio guardado ayer con el precio actual de la Gamma API).
    2. Google News RSS devuelve al menos 1 artículo reciente (<24h) sobre
       el tema del mercado (confirma que el movimiento fue por una noticia
       real, no por un error de liquidez o spam).

  Dirección del trade:
    - Si el precio subió >15pp  → compramos NO (fade del alza).
    - Si el precio bajó  >15pp  → compramos YES (fade de la baja).

Sin lookahead bias:
  - Usamos SIEMPRE el precio guardado del run anterior como referencia.
  - El precio de entrada es el precio actual de mercado (no futuro).
  - Google News RSS solo devuelve artículos ya publicados.
"""
from __future__ import annotations

import time
import urllib.parse
import xml.etree.ElementTree as ET
import requests
from datetime import datetime, timezone, timedelta

GAMMA_BASE = "https://gamma-api.polymarket.com"
HEADERS    = {"Accept": "application/json", "User-Agent": "paper-trading-bot/1.0"}

MOVE_THRESHOLD = 0.15   # 15 puntos de probabilidad = overreaction
NEWS_WINDOW_H  = 36     # buscar noticias en las últimas 36h


# ── CoinGecko / Gamma API ─────────────────────────────────────────────────────

def get_active_markets(limit: int = 100) -> list[dict]:
    """Obtiene mercados activos de Polymarket ordenados por volumen 24h."""
    try:
        r = requests.get(
            f"{GAMMA_BASE}/markets",
            params={
                "active"    : "true",
                "closed"    : "false",
                "limit"     : limit,
                "order"     : "volume24hr",
                "ascending" : "false",
            },
            headers=HEADERS,
            timeout=15,
        )
        r.raise_for_status()
        data = r.json()
        if isinstance(data, list):
            return data
        return data.get("markets", data.get("data", []))
    except Exception as e:
        print(f"[strategy] Error obteniendo mercados: {e}")
        return []


def parse_yes_price(market: dict) -> float | None:
    """Extrae la probabilidad actual del outcome YES (o el favorito)."""
    outcomes       = market.get("outcomes", "[]")
    outcome_prices = market.get("outcomePrices", "[]")

    if isinstance(outcomes, str):
        import json
        try:
            outcomes       = json.loads(outcomes)
            outcome_prices = json.loads(outcome_prices)
        except Exception:
            return None

    if not outcomes or not outcome_prices:
        return None

    for out, pr in zip(outcomes, outcome_prices):
        if out.lower() == "yes":
            try:
                p = float(pr)
                if 0.01 <= p <= 0.99:
                    return p
            except (ValueError, TypeError):
                pass

    # Si no hay YES explícito, tomar el primer outcome
    try:
        p = float(outcome_prices[0])
        if 0.01 <= p <= 0.99:
            return p
    except (ValueError, TypeError, IndexError):
        pass

    return None


# ── Google News RSS ───────────────────────────────────────────────────────────

def search_recent_news(query: str, hours: int = NEWS_WINDOW_H) -> bool:
    """
    Retorna True si hay al menos 1 artículo reciente en Google News RSS
    sobre la consulta dada. Proxy de actividad de noticias reciente.
    """
    try:
        encoded = urllib.parse.quote(query)
        url     = (
            f"https://news.google.com/rss/search"
            f"?q={encoded}&hl=en-US&gl=US&ceid=US:en"
        )
        r = requests.get(url, headers={**HEADERS, "Accept": "application/rss+xml"}, timeout=10)
        if r.status_code != 200:
            return False

        root  = ET.fromstring(r.content)
        items = root.findall(".//item")
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)

        for item in items[:10]:  # solo revisamos los 10 más recientes
            pub_raw = item.findtext("pubDate", "")
            try:
                from email.utils import parsedate_to_datetime
                pub_dt = parsedate_to_datetime(pub_raw)
                if pub_dt >= cutoff:
                    title = item.findtext("title", "")
                    print(f"    [news] ✓ '{title[:70]}'")
                    return True
            except Exception:
                continue

    except Exception as e:
        print(f"    [news] Error buscando '{query[:40]}': {e}")

    return False


# ── Señal principal ───────────────────────────────────────────────────────────

def _extract_news_keywords(question: str) -> str:
    """Extrae 3-4 palabras clave del título del mercado para buscar en Google News."""
    # Remover stop words comunes en preguntas de Polymarket
    stop = {"will", "the", "a", "an", "be", "in", "by", "to", "of", "on",
            "at", "is", "are", "win", "lose", "for", "with", "or", "and"}
    words = [w for w in question.split() if w.lower().rstrip("?") not in stop]
    return " ".join(words[:5])


def detect_fade_signals(
    markets      : list[dict],
    prev_prices  : dict[str, float],  # condition_id → precio YES de ayer
    top_n        : int   = 5,
    min_vol_24h  : float = 10_000,    # $10k volumen mínimo
) -> tuple[list[dict], dict[str, float]]:
    """
    Retorna (señales_fade, precios_actuales).

    precios_actuales: dict con todos los condition_id → precio YES de HOY,
    para guardarlo como prev_prices en el próximo run.

    Cada señal_fade tiene:
      condition_id, question, direction ("YES" o "NO"),
      price (precio de entrada), move (cuánto se movió), volume_24h
    """
    current_prices: dict[str, float] = {}
    candidates: list[dict] = []

    for m in markets:
        try:
            cond_id = m.get("conditionId") or m.get("id", "")
            if not cond_id:
                continue

            vol = float(m.get("volume24hr") or m.get("volume") or 0)
            if vol < min_vol_24h:
                continue

            if m.get("closed") or m.get("resolved"):
                continue

            yes_price = parse_yes_price(m)
            if yes_price is None:
                continue

            current_prices[cond_id] = yes_price

            # Sin precio previo: no podemos calcular movimiento
            if cond_id not in prev_prices:
                continue

            move = yes_price - prev_prices[cond_id]

            if abs(move) < MOVE_THRESHOLD:
                continue

            question = m.get("question", m.get("title", "Unknown"))

            # Dirección del fade: si subió, vendemos YES (compramos NO)
            # Si bajó, compramos YES
            direction    = "NO"  if move > 0 else "YES"
            entry_price  = (1.0 - yes_price) if direction == "NO" else yes_price

            candidates.append({
                "condition_id" : cond_id,
                "question"     : question[:80],
                "direction"    : direction,
                "price"        : entry_price,
                "yes_price"    : yes_price,
                "move"         : move,
                "volume_24h"   : vol,
                "end_date"     : m.get("endDate", m.get("endDateIso", "")),
            })

        except Exception as e:
            print(f"[strategy] Error procesando mercado: {e}")
            continue

    # Ordenar por magnitud del movimiento (los mayores overreactions primero)
    candidates.sort(key=lambda x: abs(x["move"]), reverse=True)

    print(f"\n[strategy] {len(candidates)} mercados con movimiento >{MOVE_THRESHOLD:.0%} en 24h")

    # Filtrar por confirmación de noticias
    confirmed: list[dict] = []
    for c in candidates:
        if len(confirmed) >= top_n:
            break

        keywords = _extract_news_keywords(c["question"])
        print(f"  [{c['direction']} fade] {c['question'][:55]}  move={c['move']:+.3f}  vol=${c['volume_24h']:,.0f}")
        print(f"    Buscando noticias: '{keywords}'")

        has_news = search_recent_news(keywords, hours=NEWS_WINDOW_H)
        if has_news:
            confirmed.append(c)
            print(f"    → Confirmado con noticias ✓")
        else:
            print(f"    → Sin noticias recientes — descartado")

        time.sleep(1.0)  # no spamear Google

    if confirmed:
        print(f"\n[strategy] {len(confirmed)} señales fade confirmadas:")
        for c in confirmed:
            print(f"  {c['direction']} @ {c['price']:.3f}  — {c['question'][:60]}")
    else:
        print("[strategy] Sin señales fade confirmadas por noticias")

    return confirmed, current_prices
