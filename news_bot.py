#!/usr/bin/env python3
"""
Daily World News Bot
---------------------
Fetches news from multiple free sources (Google News RSS by default,
optionally GNews.io / NewsData.io if API keys are provided), asks a free
LLM (Groq by default) to dedupe + rank + summarize the most important
stories worldwide, and sends the top N to a Telegram chat.

Run manually:
    python news_bot.py

Environment variables (see .env.example / README.md):
    GROQ_API_KEY          - required (free key from console.groq.com)
    TELEGRAM_BOT_TOKEN    - required (from @BotFather)
    TELEGRAM_CHAT_ID      - required (your chat/channel id)
    GNEWS_API_KEY         - optional, adds GNews.io as an extra source
    NEWSDATA_API_KEY      - optional, adds NewsData.io as an extra source
    TOP_N                 - optional, default 20
    GROQ_MODEL            - optional, default "openai/gpt-oss-120b"
"""

import os
import re
import json
import time
import html
import difflib
import logging
from datetime import datetime, timezone

import requests
import feedparser

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("news_bot")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

GNEWS_API_KEY = os.environ.get("GNEWS_API_KEY", "")
NEWSDATA_API_KEY = os.environ.get("NEWSDATA_API_KEY", "")

TOP_N = int(os.environ.get("TOP_N", "20"))

# Google News RSS is free, needs no API key, and covers the whole world.
# Feel free to add/remove topics or country editions.
GOOGLE_NEWS_FEEDS = {
    "World": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en-US&gl=US&ceid=US:en",
    "Business": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en-US&gl=US&ceid=US:en",
    "Technology": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en-US&gl=US&ceid=US:en",
    "Science": "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en-US&gl=US&ceid=US:en",
    "Health": "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=en-US&gl=US&ceid=US:en",
    "Top Stories": "https://news.google.com/rss?hl=en-US&gl=US&ceid=US:en",
    "India": "https://news.google.com/rss/headlines/section/topic/NATION?hl=en-IN&gl=IN&ceid=IN:en",
}


# ---------------------------------------------------------------------------
# 1. Fetch
# ---------------------------------------------------------------------------

def fetch_google_news():
    articles = []
    for category, url in GOOGLE_NEWS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries[:25]:
                title = html.unescape(re.sub(r"\s+-\s+[^-]+$", "", entry.title))  # strip " - Source" suffix
                source = ""
                if " - " in entry.title:
                    source = entry.title.rsplit(" - ", 1)[-1]
                articles.append({
                    "title": title.strip(),
                    "link": entry.link,
                    "source": source or "Google News",
                    "category": category,
                    "published": entry.get("published", ""),
                })
        except Exception as e:
            log.warning(f"Failed to fetch Google News feed '{category}': {e}")
    log.info(f"Fetched {len(articles)} articles from Google News RSS")
    return articles


def fetch_gnews():
    if not GNEWS_API_KEY:
        return []
    articles = []
    try:
        resp = requests.get(
            "https://gnews.io/api/v4/top-headlines",
            params={"lang": "en", "max": 25, "apikey": GNEWS_API_KEY},
            timeout=20,
        )
        resp.raise_for_status()
        for item in resp.json().get("articles", []):
            articles.append({
                "title": item.get("title", "").strip(),
                "link": item.get("url", ""),
                "source": (item.get("source") or {}).get("name", "GNews"),
                "category": "General",
                "published": item.get("publishedAt", ""),
            })
    except Exception as e:
        log.warning(f"GNews fetch failed: {e}")
    log.info(f"Fetched {len(articles)} articles from GNews")
    return articles


def fetch_newsdata():
    if not NEWSDATA_API_KEY:
        return []
    articles = []
    try:
        resp = requests.get(
            "https://newsdata.io/api/1/latest",
            params={"apikey": NEWSDATA_API_KEY, "language": "en"},
            timeout=20,
        )
        resp.raise_for_status()
        for item in resp.json().get("results", []):
            articles.append({
                "title": (item.get("title") or "").strip(),
                "link": item.get("link", ""),
                "source": item.get("source_id", "NewsData"),
                "category": (item.get("category") or ["General"])[0],
                "published": item.get("pubDate", ""),
            })
    except Exception as e:
        log.warning(f"NewsData fetch failed: {e}")
    log.info(f"Fetched {len(articles)} articles from NewsData.io")
    return articles


# ---------------------------------------------------------------------------
# 2. Dedupe (near-duplicate titles across sources)
# ---------------------------------------------------------------------------

def dedupe(articles, threshold=0.75):
    unique = []
    seen_titles = []
    for art in articles:
        if not art["title"] or len(art["title"]) < 8:
            continue
        norm = art["title"].lower().strip()
        is_dup = any(
            difflib.SequenceMatcher(None, norm, seen).ratio() > threshold
            for seen in seen_titles
        )
        if not is_dup:
            unique.append(art)
            seen_titles.append(norm)
    log.info(f"Deduped {len(articles)} -> {len(unique)} articles")
    return unique


# ---------------------------------------------------------------------------
# 3. Rank + summarize with Groq
# ---------------------------------------------------------------------------

def rank_with_llm(articles, top_n=TOP_N):
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not set")

    # Cap list size so the prompt stays well within free-tier token limits
    candidates = articles[:180]
    numbered = "\n".join(
        f"{i+1}. [{a['category']}] {a['title']} (source: {a['source']})"
        for i, a in enumerate(candidates)
    )

    system_prompt = (
        "You are a sharp, neutral world-news editor. You will be given a numbered list "
        "of today's headlines from many sources. Select the most globally significant, "
        "diverse stories of the day (avoid picking near-duplicates or too many stories "
        "from one topic/region). Write for a smart general reader who wants to be "
        "informed in under 5 minutes."
    )
    user_prompt = (
        f"Here are today's headlines:\n\n{numbered}\n\n"
        f"Pick the top {top_n} stories overall. For each, respond ONLY with a JSON array "
        f"(no markdown, no commentary) of objects with these exact keys:\n"
        f'  "rank": integer (1-{top_n})\n'
        f'  "headline_number": the number from the list above this story corresponds to\n'
        f'  "title": a clear, punchy rewritten headline (max ~15 words)\n'
        f'  "summary": 1-2 sentence plain-English summary of why it matters\n'
        f'  "category": short category label (World, Business, Tech, Science, Health, etc.)\n'
        f"Order the array by rank, most important first. Respond with ONLY the JSON array."
    )

    resp = requests.post(
        GROQ_URL,
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": GROQ_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.3,
            "max_tokens": 3000,
        },
        timeout=60,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"].strip()

    # Strip accidental markdown code fences
    content = re.sub(r"^```json\s*|^```\s*|```$", "", content, flags=re.MULTILINE).strip()

    try:
        ranked = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if not match:
            raise RuntimeError(f"Could not parse LLM output as JSON:\n{content[:500]}")
        ranked = json.loads(match.group(0))

    # Attach original link back onto each ranked item
    for item in ranked:
        idx = item.get("headline_number")
        if isinstance(idx, int) and 1 <= idx <= len(candidates):
            item["link"] = candidates[idx - 1]["link"]
            item["source"] = candidates[idx - 1]["source"]
        else:
            item["link"] = ""
            item["source"] = ""

    return ranked[:top_n]


# ---------------------------------------------------------------------------
# 4. Format for Telegram
# ---------------------------------------------------------------------------

def format_message(ranked):
    today = datetime.now(timezone.utc).astimezone().strftime("%A, %d %B %Y")
    lines = [f"🗞️ *Top {len(ranked)} World News — {today}*\n"]
    for item in ranked:
        rank = item.get("rank", "?")
        title = item.get("title", "Untitled").strip()
        summary = item.get("summary", "").strip()
        category = item.get("category", "")
        link = item.get("link", "")
        source = item.get("source", "")

        lines.append(f"*{rank}. {escape_md(title)}*")
        if category:
            lines.append(f"_{escape_md(category)}_")
        if summary:
            lines.append(escape_md(summary))
        if link:
            lines.append(f"[Read more]({link}) — {escape_md(source)}")
        lines.append("")  # blank line between items

    return "\n".join(lines)


def escape_md(text):
    # Escape Telegram Markdown v1 special chars minimally (keeping it simple/readable)
    return text.replace("_", "-").replace("*", "").replace("[", "(").replace("]", ")")


def chunk_message(text, limit=4000):
    """Telegram caps messages at 4096 chars; split on blank lines to stay under it."""
    chunks = []
    current = ""
    for block in text.split("\n\n"):
        if len(current) + len(block) + 2 > limit:
            chunks.append(current.strip())
            current = ""
        current += block + "\n\n"
    if current.strip():
        chunks.append(current.strip())
    return chunks


# ---------------------------------------------------------------------------
# 5. Send to Telegram
# ---------------------------------------------------------------------------

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        raise RuntimeError("TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    for chunk in chunk_message(text):
        resp = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": chunk,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
            timeout=20,
        )
        if not resp.ok:
            log.error(f"Telegram send failed: {resp.status_code} {resp.text}")
            resp.raise_for_status()
        time.sleep(0.5)  # be gentle with Telegram's rate limit


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    log.info("Starting daily news run...")

    all_articles = []
    all_articles += fetch_google_news()
    all_articles += fetch_gnews()
    all_articles += fetch_newsdata()

    if not all_articles:
        raise RuntimeError("No articles fetched from any source — aborting.")

    unique_articles = dedupe(all_articles)

    log.info(f"Ranking top {TOP_N} with Groq model '{GROQ_MODEL}'...")
    ranked = rank_with_llm(unique_articles, top_n=TOP_N)

    message = format_message(ranked)
    log.info("Sending to Telegram...")
    send_telegram(message)

    log.info("Done. ✅")


if __name__ == "__main__":
    main()
