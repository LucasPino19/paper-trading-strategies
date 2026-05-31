"""
Señal de momentum para memecoins via CoinGecko API (gratis, sin API key).

Sin lookahead bias:
  - La señal usa el retorno de los últimos 7 días completos.
  - El precio de ejecución es el último precio disponible (cierre de hoy/ayer).
  - Nunca se usa precio futuro para tomar la decisión.
"""
from __future__ import annotations

import time
import requests
from typing import Optional

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
HEADERS = {"Accept": "application/json", "User-Agent": "paper-trading-bot/1.0"}

# Categorías de memecoins en CoinGecko
CATEGORIES = ["meme-token", "dog-themed-coins", "cat-themed-coins", "frog-themed-coins"]


def get_top_memecoins(per_page: int = 30) -> list[dict]:
    """Obtiene top memecoins por market cap con sus retornos de 7d."""
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
        time.sleep(1.5)  # respetar rate limit

    coins = list(all_coins.values())
    print(f"[strategy] {len(coins)} memecoins únicas obtenidas")
    return coins


def compute_momentum_top(
    top_n    : int   = 5,
    min_mcap : float = 50_000_000,   # mínimo $50M market cap (filtrar micro-caps)
    min_vol  : float = 1_000_000,    # mínimo $1M volumen 24h
) -> tuple[list[dict], list[dict]]:
    """
    Retorna (seleccionados, todos) donde cada elemento tiene:
      id, symbol, name, current_price, price_7d_pct, market_cap, volume
    """
    coins = get_top_memecoins(per_page=50)

    scored = []
    for c in coins:
        p7 = c.get("price_change_percentage_7d_in_currency")
        mcap = c.get("market_cap") or 0
        vol  = c.get("total_volume") or 0

        if p7 is None:
            continue
        if mcap < min_mcap:
            continue
        if vol < min_vol:
            continue
        # Excluir pumps extremos (>1000% en 7d = probable manipulación)
        if p7 > 1000:
            continue

        scored.append({
            "id"          : c["id"],
            "symbol"      : c["symbol"].upper(),
            "name"        : c["name"],
            "current_price": c["current_price"],
            "price_7d_pct": p7,
            "market_cap"  : mcap,
            "volume_24h"  : vol,
        })

    scored.sort(key=lambda x: x["price_7d_pct"], reverse=True)

    # Solo entrar en memecoins con momentum positivo
    positivos = [c for c in scored if c["price_7d_pct"] > 0]
    selected  = positivos[:top_n]

    if selected:
        print(f"[strategy] Top {len(selected)} memecoins seleccionadas:")
        for c in selected:
            print(f"  {c['symbol']:<8} ${c['current_price']:<14.6g} 7d: {c['price_7d_pct']:+.1f}%")
    else:
        print("[strategy] Sin memecoins con momentum positivo esta semana")

    return selected, scored
