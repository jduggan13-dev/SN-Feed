#!/usr/bin/env python3
"""
Build a Protopage-friendly RSS 2.0 feed of current SpaceNews articles.

Replace this file entirely. Do not paste it under the old script.
"""

import html
import re
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from time import time
from urllib.parse import urlencode
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
    "Cache-Control": "no-cache, no-store, max-age=0",
    "Pragma": "no-cache",
}

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


def strip_tags(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def rfc2822(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return format_datetime(dt.astimezone(timezone.utc))


def parse_wp_date(value):
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
    def __init__(self, title, link, description, pub, guid):
        self.title = title
        self.link = link
        self.description = description
        self.pub = pub
        self.guid = guid


def fetch_json(url, timeout=25):
    resp = requests.get(url, headers=HEADERS, timeout=timeout)
    print("GET %s -> %s" % (url, resp.status_code))
    if resp.status_code == 429:
        return None
    resp.raise_for_status()
    return resp.json()


def articles_from_wp_api():
    params = {
        "per_page": MAX_ITEMS,
        "_fields": "id,date_gmt,date,link,title,excerpt,guid",
        "orderby": "date",
        "order": "desc",
        "status": "publish",
        "_": str(int(time())),
    }
    url = "%s?%s" % (WP_API, urlencode(params))
    data = fetch_json(url)
    if not data:
        return []

    out = []
    for post in data:
        title = strip_tags(post.get("title", {}).get("rendered", ""))
        link = post.get("link") or ""
        excerpt = strip_tags(post.get("excerpt", {}).get("rendered", ""))
        date_raw = post.get("date_gmt") or post.get("date") or ""
        pub = parse_wp_date(date_raw)
        guid = str(post.get("id") or link)
        if title and link:
            out.append(Article(title, link, excerpt, pub, guid))
    out.sort(key=lambda a: a.pub, reverse=True)
    print("WP API articles: %s" % len(out))
    for art in out[:3]:
        print("  newest: %s | %s" % (art.pub.isoformat(), art.title))
    return out


ARTICLE_HREF = re.compile(
    r'href="(https://spacenews.com/([a-z0-9][a-z0-9\-]+)/)"',
    re.I,
)


def articles_from_homepage():
    try:
        resp = requests.get(HOMEPAGE, headers=HEADERS, timeout=25)
        print("GET %s -> %s" % (HOMEPAGE, resp.status_code))
        if resp.status_code == 429:
            return []
        resp.raise_for_status()
    except requests.RequestException as exc:
        print("Homepage fetch failed: %s" % exc)
        return []

    html_text = resp.text
    seen = {}
    now = datetime.now(timezone.utc)

    for match in ARTICLE_HREF.finditer(html_text):
        url, slug = match.group(1), match.group(2).lower()
        if slug in SKIP_SLUGS or slug.startswith("section"):
            continue
        if url in seen:
            continue
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
    print("Homepage article-like links: %s" % len(out))
    return out


def articles_from_official_rss():
    try:
        resp = requests.get(OFFICIAL_RSS, headers=HEADERS, timeout=25)
        print("GET %s -> %s" % (OFFICIAL_RSS, resp.status_code))
        if resp.status_code == 429:
            return []
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
    except Exception as exc:
        print("Official RSS fetch/parse failed: %s" % exc)
        return []

    channel = root.find("channel")
    if channel is None:
        return []

    out = []
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
    print("Official RSS articles: %s" % len(out))
    return out


def merge_articles(primary, extras):
    by_link = {}
    for art in primary + extras:
        key = art.link.rstrip("/")
        existing = by_link.get(key)
        if existing is None:
            by_link[key] = art
        else:
            if len(art.description) > len(existing.description):
                existing.description = art.description
            if existing.pub.year >= 2026 and art.title and len(art.title) > len(existing.title):
                existing.title = art.title
    items = list(by_link.values())
    items.sort(key=lambda a: a.pub, reverse=True)
    return items[:MAX_ITEMS]


def articles_from_existing_feed():
    if not OUTPUT_FILE.exists():
        return []
    try:
        root = ET.parse(OUTPUT_FILE).getroot()
    except ET.ParseError:
        return []
    out = []
    for item in root.findall("./channel/item"):
        title = strip_tags(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        desc = strip_tags(item.findtext("description") or "")
        guid = item.findtext("guid") or link
        raw = item.findtext("pubDate")
        pub = datetime.now(timezone.utc)
        if raw:
            try:
                pub = parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                pass
        if title and link:
            out.append(Article(title, link, desc, pub, guid))
    print("Existing feed.xml articles: %s" % len(out))
    return out


def newest_pub(articles):
    if not articles:
        return None
    return max(a.pub for a in articles)


def write_rss(articles):
    now = datetime.now(timezone.utc)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">',
        "<channel>",
        "<title>SpaceNews (current articles)</title>",
        "<link>https://spacenews.com/</link>",
        "<description>Current SpaceNews articles rebuilt from the WordPress REST API for Protopage.</description>",
        "<lastBuildDate>%s</lastBuildDate>" % rfc2822(now),
        "<language>en-US</language>",
        "<ttl>60</ttl>",
        '<atom:link href="%s" rel="self" type="application/rss+xml"/>' % escape(PROXY_FEED_URL),
    ]
    for art in articles:
        parts.extend(
            [
                "<item>",
                "<title>%s</title>" % escape(art.title),
                "<link>%s</link>" % escape(art.link),
                '<guid isPermaLink="true">%s</guid>' % escape(art.link),
                "<pubDate>%s</pubDate>" % rfc2822(art.pub),
                "<description>%s</description>" % escape(art.description),
                "</item>",
            ]
        )
    parts.extend(["</channel>", "</rss>", ""])
    OUTPUT_FILE.write_text("\n".join(parts), encoding="utf-8")
    print("Wrote %s with %s items." % (OUTPUT_FILE, len(articles)))


def main():
    api_items = []
    home_items = []
    rss_items = []

    try:
        api_items = articles_from_wp_api()
    except Exception as exc:
        print("WP API failed: %s" % exc)

    if not api_items:
        try:
            home_items = articles_from_homepage()
        except Exception as exc:
            print("Homepage scrape failed: %s" % exc)
        try:
            rss_items = articles_from_official_rss()
        except Exception as exc:
            print("Official RSS fallback failed: %s" % exc)

    existing_items = articles_from_existing_feed()
    merged = merge_articles(api_items, home_items + rss_items + existing_items)

    if not merged:
        if OUTPUT_FILE.exists():
            print("No new articles collected; keeping existing feed.xml")
            return
        raise SystemExit("No articles collected and no existing feed.xml to keep.")

    incoming_newest = newest_pub(merged)
    existing_newest = newest_pub(existing_items)
    print("Merged newest: %s | %s" % (
        incoming_newest.isoformat() if incoming_newest else "n/a",
        merged[0].title,
    ))
    if existing_newest:
        print("Existing newest: %s" % existing_newest.isoformat())

    write_rss(merged)


if __name__ == "__main__":
    main()
