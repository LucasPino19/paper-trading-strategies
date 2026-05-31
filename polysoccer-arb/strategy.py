"""
Polymarket Soccer — Arbitraje vs casas de apuestas (The Odds API).

Fundamento:
  Las casas de apuestas (especialmente Pinnacle) son consideradas el mercado
  más eficiente para fútbol — su precio de cierre predice el resultado mejor
  que casi cualquier otro predictor. Si Polymarket difiere del consenso de
  bookmakers en >8pp, hay una ineficiencia explotable:

    - Polymarket > bookmaker + 8pp → Polymarket sobrevalúa ese outcome → comprar NO
    - Polymarket < bookmaker − 8pp → Polymarket subvalúa ese outcome → comprar YES

  Edge = "beating the closing line" — técnica usada por bettors profesionales.

API key:
  Requiere ODDS_API_KEY en variables de entorno (gratis en the-odds-api.com,
  500 requests/mes en free tier — suficiente para 5 ligas × 30 días).

Sin lookahead bias:
  - Usamos probabilidades actuales de ambas fuentes (ya publicadas).
  - El precio de entrada es el precio actual de Polymarket.
"""
from __future__ import annotations

import json
import os
import difflib
import requests
import time

GAMMA_BASE = "https://gamma-api.polymarket.com"
ODDS_BASE  = "https://api.the-odds-api.com/v4"
HEADERS    = {"Accept": "application/json", "User-Agent": "paper-trading-bot/1.0"}

# Ligas soportadas por The Odds API (sport key → nombre)
SOCCER_SPORTS = {
    "soccer_epl"                : "Premier League",
    "soccer_uefa_champs_league" : "Champions League",
    "soccer_spain_la_liga"      : "La Liga",
    "soccer_germany_bundesliga" : "Bundesliga",
    "soccer_italy_serie_a"      : "Serie A",
}

EDGE_THRESHOLD = 0.08   # 8pp de diferencia mínima para entrar
MIN_VOL_24H    = 5_000


# ── The Odds API ──────────────────────────────────────────────────────────────

def get_bookmaker_odds(api_key: str) -> list[dict]:
    """
    Descarga probabilidades implícitas de las mejores casas de apuestas
    para los próximos partidos de las 5 ligas principales.
    Retorna lista de {home, away, home_prob, away_prob, draw_prob, sport}.
    """
    all_matches = []

    for sport_key, sport_name in SOCCER_SPORTS.items():
        try:
            r = requests.get(
                f"{ODDS_BASE}/sports/{sport_key}/odds/",
                params={
                    "apiKey"     : api_key,
                    "regions"    : "eu",
                    "markets"    : "h2h",
                    "oddsFormat" : "decimal",
                },
                headers=HEADERS,
                timeout=15,
            )
            if r.status_code == 401:
                print(f"[strategy] ODDS_API_KEY inválida o expirada")
                break
            if r.status_code == 422:
                continue  # sport no disponible ahora
            r.raise_for_status()

            for event in r.json():
                home = event.get("home_team", "")
                away = event.get("away_team", "")
                if not home or not away:
                    continue

                # Agregar probabilidades de todos los bookmakers y promediar
                home_probs, away_probs, draw_probs = [], [], []
                for bm in event.get("bookmakers", []):
                    for mkt in bm.get("markets", []):
                        if mkt.get("key") != "h2h":
                            continue
                        for outcome in mkt.get("outcomes", []):
                            odds = outcome.get("price", 0)
                            if odds <= 0:
                                continue
                            implied = 1 / odds
                            name = outcome.get("name", "")
                            if name == home:
                                home_probs.append(implied)
                            elif name == away:
                                away_probs.append(implied)
                            else:
                                draw_probs.append(implied)

                if not home_probs or not away_probs:
                    continue

                # Promedio simple entre bookmakers (sin vig adjustment — conservador)
                hp = sum(home_probs) / len(home_probs)
                ap = sum(away_probs) / len(away_probs)
                dp = sum(draw_probs) / len(draw_probs) if draw_probs else 0

                # Normalizar para que sumen ~1
                total = hp + ap + dp
                if total > 0:
                    hp /= total
                    ap /= total
                    dp /= total

                all_matches.append({
                    "home"      : home,
                    "away"      : away,
                    "home_prob" : hp,
                    "away_prob" : ap,
                    "draw_prob" : dp,
                    "sport"     : sport_name,
                    "event_id"  : event.get("id", ""),
                })

            time.sleep(0.5)

        except Exception as e:
            print(f"[strategy] Error en {sport_name}: {e}")
            continue

    print(f"[strategy] {len(all_matches)} partidos con odds de bookmakers")
    return all_matches


# ── Polymarket ────────────────────────────────────────────────────────────────

def get_soccer_markets_poly(limit: int = 200) -> list[dict]:
    SOCCER_KW = ["premier league", "champions league", "la liga", "bundesliga",
                 "serie a", "soccer", "football", "beat", " vs ", " v "]
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
            if any(kw in (m.get("question","") + " " + m.get("title","")).lower()
                   for kw in SOCCER_KW)]


def _best_outcome_match(name: str, candidates: list[str]) -> tuple[str, float]:
    """Fuzzy match entre un nombre de equipo y una lista de candidatos."""
    matches = difflib.get_close_matches(name.lower(),
                                        [c.lower() for c in candidates],
                                        n=1, cutoff=0.4)
    if matches:
        idx   = [c.lower() for c in candidates].index(matches[0])
        ratio = difflib.SequenceMatcher(None, name.lower(), matches[0]).ratio()
        return candidates[idx], ratio
    return "", 0.0


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


# ── Señal principal ───────────────────────────────────────────────────────────

def find_arb_signals(top_n: int = 5) -> list[dict]:
    """
    Compara probabilidades de Polymarket vs bookmakers.
    Retorna señales donde la diferencia supera EDGE_THRESHOLD.
    """
    api_key = os.environ.get("ODDS_API_KEY", "")
    if not api_key:
        print("[strategy] ODDS_API_KEY no configurada — sin señales")
        return []

    bm_matches  = get_bookmaker_odds(api_key)
    poly_markets = get_soccer_markets_poly()

    print(f"[strategy] {len(poly_markets)} mercados de fútbol en Polymarket")

    signals = []

    for m in poly_markets:
        try:
            vol = float(m.get("volume24hr") or m.get("volume") or 0)
            if vol < MIN_VOL_24H:
                continue

            question = m.get("question", m.get("title", ""))
            pairs    = _parse_poly_outcomes(m)
            if len(pairs) < 2:
                continue

            # Intentar matchear el mercado de Polymarket con algún partido de bookmakers
            best_bm    = None
            best_score = 0.0

            for bm in bm_matches:
                # Buscar nombres de equipos en la pregunta de Polymarket
                q_lower = question.lower()
                home_in_q = bm["home"].lower() in q_lower or difflib.SequenceMatcher(
                    None, bm["home"].lower(), q_lower).ratio() > 0.5
                away_in_q = bm["away"].lower() in q_lower or difflib.SequenceMatcher(
                    None, bm["away"].lower(), q_lower).ratio() > 0.5

                if home_in_q and away_in_q:
                    score = 1.0
                elif home_in_q or away_in_q:
                    score = 0.6
                else:
                    continue

                if score > best_score:
                    best_score = score
                    best_bm    = bm

            if best_bm is None or best_score < 0.6:
                continue

            # Comparar probabilidades: buscar el outcome de Polymarket que corresponde
            # al equipo local (el favorito más frecuente en Polymarket)
            poly_yes_prob = pairs[0][1]   # favorito en Polymarket
            poly_outcome  = pairs[0][0]

            # Determinar qué prob de bookmaker corresponde
            outcome_lower = poly_outcome.lower()
            if best_bm["home"].lower() in outcome_lower:
                bm_prob = best_bm["home_prob"]
            elif best_bm["away"].lower() in outcome_lower:
                bm_prob = best_bm["away_prob"]
            else:
                bm_prob = best_bm["home_prob"]   # fallback

            diff = poly_yes_prob - bm_prob

            if abs(diff) < EDGE_THRESHOLD:
                continue

            cond_id   = m.get("conditionId") or m.get("id", "")
            direction = "NO" if diff > 0 else "YES"   # fade si Polymarket sobrevalúa
            price     = (1 - poly_yes_prob) if direction == "NO" else poly_yes_prob

            signals.append({
                "condition_id" : cond_id,
                "question"     : question[:80],
                "direction"    : direction,
                "outcome"      : poly_outcome,
                "price"        : price,
                "poly_prob"    : poly_yes_prob,
                "bm_prob"      : bm_prob,
                "edge"         : diff,
                "volume_24h"   : vol,
                "sport"        : best_bm["sport"],
                "match"        : f"{best_bm['home']} vs {best_bm['away']}",
            })

        except Exception as e:
            print(f"[strategy] Error procesando mercado: {e}")
            continue

    signals.sort(key=lambda x: abs(x["edge"]), reverse=True)
    selected = signals[:top_n]

    if selected:
        print(f"\n[strategy] {len(selected)} señales de arbitraje:")
        for s in selected:
            print(f"  [{s['direction']}] poly={s['poly_prob']:.2f} bm={s['bm_prob']:.2f} "
                  f"edge={s['edge']:+.3f}  — {s['question'][:50]}")
    else:
        print("[strategy] Sin señales de arbitraje hoy (diff < 8pp o sin matcheo)")

    return selected
