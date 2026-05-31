"""
Polymarket Soccer — Modelo Elo vs mercado.

Fundamento:
  Club Elo (clubelo.com) mantiene ratings Elo actualizados para todos los
  clubes de las principales ligas. El Elo es el predictor más simple y
  más robusto de resultados de fútbol — supera a modelos más complejos en
  la mayoría de evaluaciones out-of-sample.

  Si la probabilidad implícita de Polymarket difiere del modelo Elo en >8pp,
  el mercado está mal valuado y hay una oportunidad:
    - Polymarket > Elo + 8pp → Polymarket sobrevalúa → comprar NO
    - Polymarket < Elo − 8pp → Polymarket subvalúa  → comprar YES

  Fórmula Elo estándar con ajuste de ventaja local (+50 Elo puntos al local):
    P(local gana) = 1 / (1 + 10^((Elo_visitante + 50 - Elo_local) / 400))
    P(visitante gana) = 1 - P(local gana) - P(empate)
    P(empate) ≈ constante ~0.25 ajustada por diferencia de Elo

Sin lookahead bias:
  - Club Elo usa solo resultados anteriores a la fecha actual.
  - Las probabilidades de Polymarket son precios ya publicados.
  - No usamos resultado del partido para la señal de entrada.
"""
from __future__ import annotations

import csv
import difflib
import io
import json
import re
import requests
import time

GAMMA_BASE  = "https://gamma-api.polymarket.com"
CLUBELO_URL = "http://api.clubelo.com/"   # endpoint base = ratings actuales
HEADERS     = {"Accept": "application/json", "User-Agent": "paper-trading-bot/1.0"}

EDGE_THRESHOLD   = 0.08    # 8pp de diferencia mínima
HOME_ADVANTAGE   = 50      # Elo extra para el equipo local (estándar en literatura)
DRAW_BASE        = 0.25    # probabilidad de empate base (~promedio histórico)
MIN_VOL_24H      = 5_000
MIN_ELO_MATCHES  = 2       # requiero encontrar al menos 2 equipos en el Elo DB


# ── Club Elo ──────────────────────────────────────────────────────────────────

def download_elo_ratings() -> dict[str, float]:
    """
    Descarga los ratings Elo actuales de todos los clubes desde clubelo.com.
    Retorna dict {nombre_club_lower: elo_score}.
    """
    try:
        r = requests.get(CLUBELO_URL, headers={"User-Agent": "paper-trading-bot/1.0"},
                         timeout=15)
        r.raise_for_status()
        ratings = {}
        reader  = csv.DictReader(io.StringIO(r.text))
        for row in reader:
            club = row.get("Club", "").strip()
            elo  = row.get("Elo", "")
            if club and elo:
                try:
                    ratings[club.lower()] = float(elo)
                except ValueError:
                    pass
        print(f"[strategy] {len(ratings)} clubes en Club Elo DB")
        return ratings
    except Exception as e:
        print(f"[strategy] Error descargando Club Elo: {e}")
        return {}


def _find_elo(team_name: str, elo_db: dict[str, float]) -> tuple[float | None, str]:
    """Busca el Elo de un equipo con fuzzy matching. Retorna (elo, matched_name)."""
    if not team_name or not elo_db:
        return None, ""

    name_lower = team_name.lower()

    # Búsqueda exacta primero
    if name_lower in elo_db:
        return elo_db[name_lower], team_name

    # Fuzzy match
    candidates = list(elo_db.keys())
    matches    = difflib.get_close_matches(name_lower, candidates, n=1, cutoff=0.55)
    if matches:
        return elo_db[matches[0]], matches[0]

    # Intento con palabras clave (ej: "Manchester City" → buscar "city")
    words = name_lower.split()
    for word in reversed(words):   # últimas palabras son más distintivas
        if len(word) < 4:
            continue
        partial = [k for k in candidates if word in k]
        if len(partial) == 1:
            return elo_db[partial[0]], partial[0]

    return None, ""


# ── Probabilidades Elo ────────────────────────────────────────────────────────

def elo_to_win_prob(elo_home: float, elo_away: float) -> tuple[float, float, float]:
    """
    Calcula P(home win), P(draw), P(away win) con el modelo Elo estándar.
    Ajuste de ventaja local: +HOME_ADVANTAGE al equipo de casa.
    """
    elo_diff = (elo_home + HOME_ADVANTAGE) - elo_away

    # Probabilidad de que el local no pierda (win + draw)
    p_home_no_loss = 1 / (1 + 10 ** (-elo_diff / 400))

    # Probabilidad de empate: decrece con diferencia de Elo
    # Empírico: ~0.26 cuando los equipos son iguales, menos cuando hay más diferencia
    draw_decay = max(0.10, DRAW_BASE - abs(elo_diff) / 1500)

    p_home = p_home_no_loss - draw_decay / 2
    p_away = 1 - p_home_no_loss - draw_decay / 2
    p_draw = 1 - p_home - p_away

    # Asegurar que estén en [0, 1]
    p_home = max(0.02, min(0.96, p_home))
    p_away = max(0.02, min(0.96, p_away))
    p_draw = max(0.02, 1 - p_home - p_away)

    return p_home, p_draw, p_away


# ── Extracción de equipos de preguntas de Polymarket ─────────────────────────

# Patrones para extraer equipos de preguntas tipo:
#   "Will Real Madrid beat Barcelona?"
#   "Real Madrid vs Barcelona winner?"
#   "Will Liverpool win vs Manchester City?"
_PATTERNS = [
    r"will (.+?) (?:beat|defeat|win against|win vs\.?) (.+?)[\?\.]",
    r"(.+?) vs\.? (.+?) (?:winner|match winner|result)",
    r"(.+?) (?:vs|v) (.+?) (?:to win|winner)",
    r"will (.+?) win the match against (.+?)[\?\.]",
]

def _extract_teams(question: str) -> tuple[str, str]:
    """Intenta extraer dos nombres de equipo de la pregunta del mercado."""
    q = question.strip()
    for pattern in _PATTERNS:
        m = re.search(pattern, q, re.IGNORECASE)
        if m:
            return m.group(1).strip(), m.group(2).strip()
    return "", ""


# ── Señal principal ───────────────────────────────────────────────────────────

def _parse_poly_outcomes(m: dict) -> list[tuple[str, float]]:
    outcomes = m.get("outcomes", "[]")
    prices   = m.get("outcomePrices", "[]")
    if isinstance(outcomes, str):
        try:
            outcomes = json.loads(outcomes)
            prices   = json.loads(prices)
        except Exception:
            return []
    result = []
    for out, pr in zip(outcomes, prices):
        try:
            p = float(pr)
            if 0.01 < p < 0.99:
                result.append((out, p))
        except (ValueError, TypeError):
            pass
    return result


def get_soccer_markets_poly(limit: int = 200) -> list[dict]:
    SOCCER_KW = ["premier league", "champions league", "la liga", "bundesliga",
                 "serie a", "ligue 1", "copa", "soccer", "football",
                 "beat", " vs ", " v "]
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
        print(f"[strategy] Error Polymarket: {e}")
        return []

    return [m for m in markets
            if any(kw in (m.get("question", "") + " " + m.get("title","")).lower()
                   for kw in SOCCER_KW)]


def find_model_signals(top_n: int = 5) -> list[dict]:
    """
    Compara probabilidades Elo vs Polymarket.
    Retorna señales donde el modelo Elo difiere del mercado en >EDGE_THRESHOLD.
    """
    elo_db   = download_elo_ratings()
    markets  = get_soccer_markets_poly()
    print(f"[strategy] {len(markets)} mercados de fútbol en Polymarket")

    if not elo_db:
        print("[strategy] Sin datos Elo — abortando")
        return []

    signals  = []
    n_parsed = 0
    n_matched = 0

    for m in markets:
        try:
            vol = float(m.get("volume24hr") or m.get("volume") or 0)
            if vol < MIN_VOL_24H:
                continue
            if m.get("closed") or m.get("resolved"):
                continue

            question = m.get("question", m.get("title", ""))
            team_a, team_b = _extract_teams(question)
            if not team_a or not team_b:
                continue
            n_parsed += 1

            elo_a, matched_a = _find_elo(team_a, elo_db)
            elo_b, matched_b = _find_elo(team_b, elo_db)

            if elo_a is None or elo_b is None:
                continue
            n_matched += 1

            # Modelo Elo: team_a = local (primer equipo mencionado = local en general)
            p_home, p_draw, p_away = elo_to_win_prob(elo_a, elo_b)

            pairs = _parse_poly_outcomes(m)
            if not pairs:
                continue

            # Asignar la prob Elo al outcome de Polymarket que corresponde a team_a
            poly_prob = pairs[0][1]
            poly_outcome = pairs[0][0]

            # Si el outcome favorito corresponde al local (team_a), comparar con p_home
            # Si corresponde al visitante, comparar con p_away
            model_prob = p_home
            if team_b.lower() in poly_outcome.lower():
                model_prob = p_away

            diff = poly_prob - model_prob

            if abs(diff) < EDGE_THRESHOLD:
                continue

            cond_id   = m.get("conditionId") or m.get("id", "")
            direction = "NO" if diff > 0 else "YES"
            price     = (1 - poly_prob) if direction == "NO" else poly_prob

            signals.append({
                "condition_id" : cond_id,
                "question"     : question[:80],
                "direction"    : direction,
                "outcome"      : poly_outcome,
                "price"        : price,
                "poly_prob"    : poly_prob,
                "model_prob"   : model_prob,
                "elo_home"     : elo_a,
                "elo_away"     : elo_b,
                "matched_home" : matched_a,
                "matched_away" : matched_b,
                "edge"         : diff,
                "volume_24h"   : vol,
            })

        except Exception as e:
            print(f"[strategy] Error: {e}")
            continue

    print(f"[strategy] {n_parsed} mercados con dos equipos extraídos, {n_matched} matcheados con Elo")

    signals.sort(key=lambda x: abs(x["edge"]), reverse=True)
    selected = signals[:top_n]

    if selected:
        print(f"\n[strategy] Top {len(selected)} señales del modelo Elo:")
        for s in selected:
            print(f"  [{s['direction']}] poly={s['poly_prob']:.2f} elo={s['model_prob']:.2f} "
                  f"edge={s['edge']:+.3f}  — {s['question'][:50]}")
            print(f"    Elo: {s['matched_home']} ({s['elo_home']:.0f}) vs "
                  f"{s['matched_away']} ({s['elo_away']:.0f})")
    else:
        print("[strategy] Sin señales del modelo Elo hoy")

    return selected
