"""
Señal dual para memecoins: CoinGecko Trending × Momentum 7d.

Lógica:
  - Solo entra en memecoins que cumplen DOS condiciones simultáneamente:
    1. Están en el top de búsquedas de CoinGecko en las últimas 24h (atención social).
    2. Tienen retorno positivo en los últimos 7 días (precio confirma).
  - Trending sin precio subiendo = hype sin soporte → ignorar.
  - Precio subiendo sin trending = momentum silencioso que puede cortarse → ignorar.
  - Ambos juntos = momento de mayor probabilidad de continuación.

Sin lookahead bias:
  - El retorno 7d es un dato ya cerrado que entrega la API.
  - El precio de entrada es el último precio disponible (cierre o spot actual).
"""
from __future__ import annotations

import time
import requests
from typing import Optional

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
HEADERS = {"Accept": "application/json", "User-Agent": "paper-trading-bot/1.0"}

CATEGORIES = ["meme-token", "dog-themed-coins", "cat-themed-coins", "frog-themed-coins"]


def get_trending_coin_ids() -> set[str]:
    """
    Retorna los IDs de coins que están en el top de búsquedas de CoinGecko
    en las últimas 24 horas (proxy de atención social, gratis sin API key).
    """
    try:
        r = requests.get(
            f"{COINGECKO_BASE}/search/trending",
            headers=HEADERS,
            timeout=10,
        )
        if r.status_code == 200:
            coins = r.json().get("coins", [])
            ids = {c["item"]["id"] for c in coins}
            print(f"[strategy] {len(ids)} coins trending en CoinGecko: {ids}")
            return ids
        elif r.status_code == 429:
            print("[strategy] Rate limit en /trending — esperando 60s...")
            time.sleep(60)
    except Exception as e:
        print(f"[strategy] Error obteniendo trending: {e}")
    return set()


def get_top_memecoins(per_page: int = 50) -> list[dict]:
    """Obtiene memecoins por market cap con retornos de 7d."""
    all_coins: dict[str, dict] = {}

    for category in CATEGORIES:
        try:
            r = requests.get(
                f"{COINGECKO_BASE}/coins/markets",
                params={
                    "vs_currency"             : "usd",
                    "category"                : category,
                    "order"                   : "market_cap_desc",
                    "per_page"                : per_page,
                    "price_change_percentage" : "7d",
                },
                headers=HEADERS,
                timeout=15,
            )
            if r.status_code == 200:
                for c in r.json():
                    if c["id"] not in all_coins:
                        all_coins[c["id"]] = c
            elif r.status_code == 429:
                print("[strategy] Rate limit CoinGecko — esperando 60s...")
                time.sleep(60)
        except Exception as e:
            print(f"[strategy] Error en categoría {category}: {e}")
        time.sleep(1.5)

    print(f"[strategy] {len(all_coins)} memecoins únicas obtenidas de todas las categorías")
    return list(all_coins.values())


def compute_momentum_top(
    top_n    : int   = 5,
    min_mcap : float = 50_000_000,
    min_vol  : float = 1_000_000,
) -> tuple[list[dict], list[dict]]:
    """
    Retorna (seleccionados, todos).

    Criterio de selección (doble confirmación):
      1. El coin aparece en el top de trending de CoinGecko (últimas 24h).
      2. El retorno de los últimos 7 días es positivo.

    Si hay menos de top_n coins con doble confirmación, completa con
    los de mayor momentum que al menos tienen señal de precio positiva.
    Esto evita que el bot se quede sin posiciones en semanas de baja social.
    """
    trending_ids = get_trending_coin_ids()
    coins        = get_top_memecoins(per_page=50)

    scored = []
    for c in coins:
        p7   = c.get("price_change_percentage_7d_in_currency")
        mcap = c.get("market_cap") or 0
        vol  = c.get("total_volume") or 0

        if p7 is None or mcap < min_mcap or vol < min_vol:
            continue
        if p7 > 1000:  # excluir pumps extremos = probable manipulación
            continue

        is_trending = c["id"] in trending_ids

        scored.append({
            "id"           : c["id"],
            "symbol"       : c["symbol"].upper(),
            "name"         : c["name"],
            "current_price": c["current_price"],
            "price_7d_pct" : p7,
            "market_cap"   : mcap,
            "volume_24h"   : vol,
            "is_trending"  : is_trending,
            # Score compuesto: trending vale 30pp extra en el ranking
            "score"        : p7 + (30.0 if is_trending else 0.0),
        })

    # Ordenar por score compuesto (trending + momentum)
    scored.sort(key=lambda x: x["score"], reverse=True)

    # Solo entrar con momentum positivo
    positivos = [c for c in scored if c["price_7d_pct"] > 0]

    # Primero: coins con doble confirmación (trending Y precio positivo)
    dual_signal = [c for c in positivos if c["is_trending"]]
    solo_price  = [c for c in positivos if not c["is_trending"]]

    if len(dual_signal) >= top_n:
        selected = dual_signal[:top_n]
    elif dual_signal:
        # Completar con los mejores de solo precio si no llegan a top_n
        selected = dual_signal + solo_price[:top_n - len(dual_signal)]
    else:
        # Sin ninguno trending esta semana — usar solo precio como fallback
        print("[strategy] Ninguna memecoin trending esta semana — usando solo momentum 7d")
        selected = positivos[:top_n]

    if selected:
        print(f"\n[strategy] Top {len(selected)} memecoins seleccionadas (🔥=trending+momentum, 📈=solo momentum):")
        for c in selected:
            tag = "🔥" if c["is_trending"] else "📈"
            print(f"  {tag} {c['symbol']:<8} ${c['current_price']:<14.6g} 7d: {c['price_7d_pct']:+.1f}%")
    else:
        print("[strategy] Sin memecoins con señal válida esta semana")

    return selected, scored
