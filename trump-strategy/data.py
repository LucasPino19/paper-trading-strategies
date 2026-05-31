"""Fuente de datos: RSS de Google News + Truth Social para detectar menciones de Trump."""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import feedparser
import yfinance as yf

_HERE = os.path.dirname(os.path.abspath(__file__))
PROCESSED_FILE = os.path.join(_HERE, "data", "processed_articles.json")

GOOGLE_NEWS_TEMPLATE = "https://news.google.com/rss/search?q={}&hl=en-US&gl=US&ceid=US:en"

TRUMP_QUERIES = [
    "Trump+stock+buy",
    "Trump+stock+market",
    '"Donald+Trump"+stock+invest',
    "Trump+Truth+Social+stock",
    "Trump+tariff+stock",
]

# Empresas que Trump menciona frecuentemente → ticker
WATCHLIST: dict[str, list[str]] = {
    "AAPL":  ["Apple", "Tim Cook"],
    "AMZN":  ["Amazon", "Bezos", "Jeff Bezos"],
    "META":  ["Meta", "Facebook", "Zuckerberg", "Mark Zuckerberg"],
    "GOOGL": ["Google", "Alphabet", "Sundar Pichai"],
    "MSFT":  ["Microsoft", "Bill Gates"],
    "NVDA":  ["Nvidia", "Jensen Huang"],
    "DELL":  ["Dell", "Michael Dell"],
    "TSLA":  ["Tesla", "Elon Musk", "Elon"],
    "GM":    ["General Motors", "Mary Barra"],
    "F":     ["Ford Motor", "Ford"],
    "LMT":   ["Lockheed Martin", "Lockheed"],
    "BA":    ["Boeing"],
    "RTX":   ["Raytheon"],
    "XOM":   ["Exxon", "ExxonMobil"],
    "CVX":   ["Chevron"],
    "JPM":   ["JPMorgan", "JP Morgan", "Jamie Dimon"],
    "GS":    ["Goldman Sachs", "Goldman"],
    "BAC":   ["Bank of America"],
    "WMT":   ["Walmart"],
    "DIS":   ["Disney", "Bob Iger"],
    "NFLX":  ["Netflix"],
    "PFE":   ["Pfizer"],
    "MRNA":  ["Moderna"],
    "X":     ["US Steel", "United States Steel"],
    "NKE":   ["Nike"],
    "SBUX":  ["Starbucks"],
    "T":     ["AT&T"],
    "VZ":    ["Verizon"],
    "MS":    ["Morgan Stanley"],
    "C":     ["Citigroup", "Citi"],
    "TM":    ["Toyota"],
    "SONY":  ["Sony"],
    "BABA":  ["Alibaba", "Jack Ma"],
}

POSITIVE_WORDS = {
    "buy", "invest", "great", "amazing", "tremendous", "beautiful", "love",
    "winner", "backing", "support", "deal", "opportunity", "bullish", "best",
    "strong", "incredible", "fantastic", "terrific", "endorse", "recommend",
    "rising", "growth", "boom", "approve", "approved", "proud", "excellent",
    "powerful", "successful", "thriving", "prosperous",
}

NEGATIVE_WORDS = {
    "sell", "bad", "corrupt", "failing", "terrible", "avoid", "crash",
    "bearish", "fake", "fraud", "bankrupt", "overpriced", "disaster",
    "horrible", "worst", "enemy", "unfair", "threatening", "lawsuit",
    "investigate", "boycott", "tariff", "sanction", "ban", "fine",
    "penalty", "block", "rigged", "scam", "loser", "weak", "failing",
}


def _load_processed() -> set[str]:
    if os.path.exists(PROCESSED_FILE):
        with open(PROCESSED_FILE) as f:
            return set(json.load(f))
    return set()


def _save_processed(ids: set[str]) -> None:
    os.makedirs(os.path.dirname(PROCESSED_FILE), exist_ok=True)
    with open(PROCESSED_FILE, "w") as f:
        json.dump(list(ids)[-500:], f)  # máximo 500 para no crecer indefinido


def fetch_trump_articles(hours: int = 4) -> list[dict]:
    """
    Obtiene artículos recientes de noticias que mencionan a Trump y acciones.
    Solo retorna artículos que NO fueron procesados antes (deduplicación).
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    processed = _load_processed()
    articles: list[dict] = []
    new_ids: set[str] = set()

    for query in TRUMP_QUERIES:
        url = GOOGLE_NEWS_TEMPLATE.format(query)
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                article_id = entry.get("id") or entry.get("link", "")
                if not article_id or article_id in processed:
                    continue
                published = entry.get("published_parsed")
                if published:
                    pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                    if pub_dt < cutoff:
                        continue
                text = f"{entry.get('title', '')} {entry.get('summary', '')}"
                articles.append({
                    "id": article_id,
                    "title": entry.get("title", ""),
                    "text": text,
                    "url": entry.get("link", ""),
                    "published": entry.get("published", ""),
                })
                new_ids.add(article_id)
        except Exception as e:
            print(f"[data] RSS falló para '{query}': {e}")

    _save_processed(processed | new_ids)
    print(f"[data] {len(articles)} artículos nuevos de {len(TRUMP_QUERIES)} feeds")
    return articles


def extract_signals(articles: list[dict]) -> list[dict]:
    """
    Analiza artículos y extrae señales de compra/venta por ticker.
    Retorna señales ordenadas por confianza descendente.
    """
    signals: list[dict] = []
    seen: set[str] = set()  # un ticker solo genera una señal por ciclo

    for article in articles:
        text = article["text"]
        text_lower = text.lower()

        if "trump" not in text_lower and "donald" not in text_lower:
            continue

        for ticker, keywords in WATCHLIST.items():
            if ticker in seen:
                continue
            stock_mentioned = (
                any(kw.lower() in text_lower for kw in keywords)
                or bool(re.search(rf'\b{re.escape(ticker)}\b', text))
            )
            if not stock_mentioned:
                continue

            pos = sum(1 for w in POSITIVE_WORDS if w in text_lower)
            neg = sum(1 for w in NEGATIVE_WORDS if w in text_lower)

            if pos == neg:
                continue  # neutral

            action = "buy" if pos > neg else "sell"
            confidence = abs(pos - neg) / max(pos + neg, 1)

            signals.append({
                "ticker": ticker,
                "action": action,
                "confidence": round(confidence, 2),
                "pos_count": pos,
                "neg_count": neg,
                "title": article["title"],
                "url": article["url"],
                "published": article["published"],
            })
            seen.add(ticker)

    return sorted(signals, key=lambda x: x["confidence"], reverse=True)


def get_current_price(ticker: str) -> Optional[float]:
    """Precio actual del ticker. Alpaca primero, yfinance como fallback."""
    import os, sys
    _root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _root not in sys.path:
        sys.path.insert(0, _root)
    try:
        from alpaca_trader import get_alpaca_price
        price = get_alpaca_price(ticker)
        if price:
            return price
    except Exception:
        pass
    try:
        price = yf.Ticker(ticker).fast_info.last_price
        if price and float(price) > 0:
            return float(price)
    except Exception:
        pass
    try:
        hist = yf.Ticker(ticker).history(period="2d")
        if not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception:
        pass
    return None
