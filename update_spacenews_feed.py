#!/usr/bin/env python3
"""
Build a Protopage-friendly RSS 2.0 feed of current SpaceNews articles.

Why this exists
---------------
https://spacenews.com/feed is a WordPress RSS endpoint that currently lags
the homepage by days and is dominated by press releases / sponsored posts.
The public WordPress REST API is current:

    https://spacenews.com/wp-json/wp/v2/posts

This script prefers that API, then optionally merges a few homepage
headlines, and only then falls back to the official RSS so a failed API
call does not wipe feed.xml.
"""

from __future__ import annotations

import html
import re
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

import requests

WP_API = "https://spacenews.com/wp-json/wp/v2/posts"
HOMEPAGE = "https://spacenews.com/"
OFFICIAL_RSS = "https://spacenews.com/feed"
OUTPUT_FILE = Path("feed.xml")
PROXY_FEED_URL = "https://jduggan13-dev.github.io/SN-Feed/feed.xml"
MAX_ITEMS = 30

HEADERS = {
    "User-Agent": "SN-Feed/2.0 (+https://github.com/jduggan13-dev/SN-Feed; personal RSS proxy)",
    "Accept": "application/json, text/html, application/rss+xml;q=0.9, */*;q=0.8",
}

# Skip obvious non-article slugs that appear as homepage links.
SKIP_SLUGS = {
    "feed",
    "subscribe",
    "newsletters",
    "about-us",
    "privacy-policy-2",
    "video",
    "space-minds-podcast",
    "newsmaker-forum",
    "spacenews-magazine",
    "sn-focus",
    "pressreleases",
    "audience",
    "editorial-calendar",
    "ad-buy",
    "advertising-contact-us",
    "spacenews-faqs",
    "media-kit-25",
    "events",
    "jobs",
    "wp-json",
    "section",
}


def strip_tags(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def rfc2822(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt.astimezone(timezone.utc))


def parse_wp_date(value: str) -> datetime:
    # WP dates look like 2026-09-10T10:00:00 (site local, no TZ).
    # SpaceNews is US-oriented; treat naive stamps as UTC-ish for feed order.
    try:
        if value.endswith("Z"):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        return datetime.now(timezone.utc)


class Article:
    def __init__(self, title: str, link: str, description: str, pub: datetime, guid: str):
        self.title = title
        self.link = link
        self.description = description
        self.pub = pub
        self.guid = guid


def fetch_json(url: str, timeout: int = 25):
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    print(f"GET {url} -> {resp.status_code}")
    if resp.status_code == 429:
        return None
    resp.raise_for_status()
    return resp.json()


def articles_from_wp_api() -> list[Article]:
    params = {
        "per_page": MAX_ITEMS,
        "_fields": "id,date_gmt,date,link,title,excerpt,guid",
        "orderby": "date",
        "order": "desc",
        "status": "publish",
    }
    # requests params encoding
    from urllib.parse import urlencode

    url = f"{WP_API}?{urlencode(params)}"
    data = fetch_json(url)
    if not data:
        return []

    out: list[Article] = []
    for post in data:
        title = strip_tags(post.get("title", {}).get("rendered", ""))
        link = post.get("link") or ""
        excerpt = strip_tags(post.get("excerpt", {}).get("rendered", ""))
        date_raw = post.get("date_gmt") or post.get("date") or ""
        pub = parse_wp_date(date_raw)
        guid = str(post.get("id") or link)
        if title and link:
            out.append(Article(title, link, excerpt, pub, guid))
    print(f"WP API articles: {len(out)}")
    if out:
        print(f"  newest: {out[0].title} ({out[0].pub.isoformat()})")
    return out


ARTICLE_HREF = re.compile(
    r'href="(https://spacenews.com/([a-z0-9][a-z0-9\-]+)/)"',
    re.I,
)


def articles_from_homepage() -> list[Article]:
    try:
        resp = requests.get(HOMEPAGE, headers=HEADERS, timeout=25)
        print(f"GET {HOMEPAGE} -> {resp.status_code}")
        if resp.status_code == 429:
            return []
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"Homepage fetch failed: {exc}")
        return []

    html_text = resp.text
    seen: dict[str, Article] = {}
    now = datetime.now(timezone.utc)

    for match in ARTICLE_HREF.finditer(html_text):
        url, slug = match.group(1), match.group(2).lower()
        if slug in SKIP_SLUGS or slug.startswith("section"):
            continue
        if url in seen:
            continue
        # Try to find nearby heading text
        start = max(0, match.start() - 400)
        chunk = html_text[start : match.end() + 200]
        title_m = re.search(
            r"<h[1-4][^>]*>\s*(?:<a[^>]*>)?\s*([^<]{8,200})",
            chunk,
            re.I,
        )
        title = strip_tags(title_m.group(1) if title_m else slug.replace("-", " ").title())
        seen[url] = Article(title, url, title, now, url)

    out = list(seen.values())
    print(f"Homepage article-like links: {len(out)}")
    return out


def articles_from_official_rss() -> list[Article]:
    try:
        resp = requests.get(OFFICIAL_RSS, headers=HEADERS, timeout=25)
        print(f"GET {OFFICIAL_RSS} -> {resp.status_code}")
        if resp.status_code == 429:
            return []
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:
        print(f"Official RSS fetch/parse failed: {exc}")
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    out: list[Article] = []
    for item in channel.findall("item"):
        title_el = item.find("title")
        link_el = item.find("link")
        desc_el = item.find("description")
        pub_el = item.find("pubDate")
        guid_el = item.find("guid")
        title = strip_tags(title_el.text if title_el is not None else "")
        link = (link_el.text or "").strip() if link_el is not None else ""
        desc = strip_tags(desc_el.text if desc_el is not None else "")
        guid = (guid_el.text or link) if guid_el is not None else link
        pub = datetime.now(timezone.utc)
        if pub_el is not None and pub_el.text:
            try:
                pub = parsedate_to_datetime(pub_el.text)
            except (TypeError, ValueError):
                pass
        if title and link:
            out.append(Article(title, link, desc, pub, guid))
    print(f"Official RSS articles: {len(out)}")
    return out


def merge_articles(primary: list[Article], extras: list[Article]) -> list[Article]:
    by_link: dict[str, Article] = {}
    for art in primary + extras:
        key = art.link.rstrip("/")
        existing = by_link.get(key)
        if existing is None:
            by_link[key] = art
        else:
            # Prefer the richer description / earlier real pub date
            if len(art.description) > len(existing.description):
                existing.description = art.description
            if art.pub and existing.pub and art.pub < existing.pub and art.pub.year >= 2020:
                # homepage uses "now"; don't let that overwrite a real date
                pass
            if existing.pub.year >= 2026 and art.title and len(art.title) > len(existing.title):
                existing.title = art.title
    items = list(by_link.values())
    items.sort(key=lambda a: a.pub, reverse=True)
    return items[:MAX_ITEMS]


def write_rss(articles: list[Article]) -> None:
    now = datetime.now(timezone.utc)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        "<title>SpaceNews (current articles)</title>",
        "<link>https://spacenews.com/</link>",
        "<description>Current SpaceNews articles rebuilt from the WordPress REST API for Protopage.</description>",
        f"<lastBuildDate>{rfc2822(now)}</lastBuildDate>",
        "<language>en-US</language>",
        "<ttl>60</ttl>",
        f'<atom:link href="{escape(PROXY_FEED_URL)}" rel="self" type="application/rss+xml"/>',
    ]
    for art in articles:
        parts.extend(
            [
                "<item>",
                f"<title>{escape(art.title)}</title>",
                f"<link>{escape(art.link)}</link>",
                f"<guid isPermaLink=\"true\">{escape(art.link)}</guid>",
                f"<pubDate>{rfc2822(art.pub)}</pubDate>",
                f"<description>{escape(art.description)}</description>",
                "</item>",
            ]
        )
    parts.extend(["</channel>", "</rss>", ""])
    OUTPUT_FILE.write_text("\n".join(parts), encoding="utf-8")
    print(f"Wrote {OUTPUT_FILE} with {len(articles)} items.")


def main() -> None:
    api_items: list[Article] = []
    home_items: list[Article] = []
    rss_items: list[Article] = []

    try:
        api_items = articles_from_wp_api()
    except Exception as exc:
        print(f"WP API failed: {exc}")

    # Homepage scrape is only a backup. Those links have no reliable pubDate
    # and would otherwise sort above real API articles.
    if not api_items:
        try:
            home_items = articles_from_homepage()
        except Exception as exc:
            print(f"Homepage scrape failed: {exc}")
        try:
            rss_items = articles_from_official_rss()
        except Exception as exc:
            print(f"Official RSS fallback failed: {exc}")

    merged = merge_articles(api_items, home_items + rss_items)

    if not merged:
        if OUTPUT_FILE.exists():
            print("No new articles collected; keeping existing feed.xml")
            return
        raise SystemExit("No articles collected and no existing feed.xml to keep.")

    write_rss(merged)


if __name__ == "__main__":
    main()
