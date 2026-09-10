import requests
from pathlib import Path
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.etree import ElementTree as ET

SPACE_NEWS_FEED = "https://spacenews.com/feed"
OUTPUT_FILE = Path("feed.xml")

def fetch_spacenews():
    headers = {"User-Agent": "Mozilla/5.0 (GitHub Actions RSS proxy)"}
    resp = requests.get(SPACE_NEWS_FEED, headers=headers, timeout=20)

    # If we're being rate-limited, don't crash the job
    if resp.status_code == 429:
        print("Received 429 Too Many Requests from SpaceNews; keeping existing feed.xml.")
        return None

    resp.raise_for_status()
    return resp.content

def simplify_rss(xml_bytes):
    # ... your existing simplify_rss, unchanged ...
    tree = ET.fromstring(xml_bytes)
    for elem in tree.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
    channel = None
    for child in tree:
        if child.tag == "channel":
            channel = child
            break
    if channel is None:
        return xml_bytes.decode("utf-8")

    items = [child for child in channel if child.tag == "item"]

    now = datetime.now(timezone.utc)
    last_build = format_datetime(now)
    items_xml = [ET.tostring(item, encoding="unicode") for item in items]

    rss_text = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>SpaceNews (GitHub proxy)</title>
    <link>https://spacenews.com/</link>
    <description>SpaceNews RSS feed proxied through GitHub for Protopage</description>
    <lastBuildDate>{last_build}</lastBuildDate>
    <language>en-US</language>
{''.join(items_xml)}
  </channel>
</rss>
"""
    return rss_text

def main():
    xml_bytes = fetch_spacenews()
    if xml_bytes is None:
        # 429 – skip update, exit successfully
        return

    rss_text = simplify_rss(xml_bytes)
    OUTPUT_FILE.write_text(rss_text, encoding="utf-8")

if __name__ == "__main__":
    main()
