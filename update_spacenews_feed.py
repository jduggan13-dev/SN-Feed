import requests
from pathlib import Path
from datetime import datetime, timezone
from email.utils import format_datetime
from xml.etree import ElementTree as ET

SPACE_NEWS_FEED = "https://spacenews.com/feed"
OUTPUT_FILE = Path("feed.xml")
PROXY_FEED_URL = "https://jduggan13-dev.github.io/SN-Feed/feed.xml"  # your proxy feed URL
MAX_ITEMS = 30  # how many of the most recent articles to keep

def fetch_spacenews():
    headers = {"User-Agent": "Mozilla/5.0 (GitHub Actions RSS proxy)"}
    resp = requests.get(SPACE_NEWS_FEED, headers=headers, timeout=20)

    if resp.status_code == 429:
        print("Received 429 Too Many Requests from SpaceNews; keeping existing feed.xml.")
        return None

    resp.raise_for_status()
    return resp.content

def main():
    xml_bytes = fetch_spacenews()
    if xml_bytes is None:
        # 429 or similar; do not overwrite existing feed.xml
        return

    # Parse with namespaces preserved
    tree = ET.fromstring(xml_bytes)

    ns = {
        'content': 'http://purl.org/rss/1.0/modules/content/',
        'wfw': 'http://wellformedweb.org/CommentAPI/',
        'dc': 'http://purl.org/dc/elements/1.1/',
        'atom': 'http://www.w3.org/2005/Atom',
        'sy': 'http://purl.org/rss/1.0/modules/syndication/',
        'slash': 'http://purl.org/rss/1.0/modules/slash/',
    }

    for prefix, uri in ns.items():
        ET.register_namespace(prefix, uri)

    channel = tree.find('channel')
    if channel is None:
        # Fallback: just write original content through
        OUTPUT_FILE.write_text(xml_bytes.decode('utf-8'), encoding='utf-8')
        return

    items = channel.findall('item')

    # Take only the top MAX_ITEMS (SpaceNews feed is newest-first)
    items = items[:MAX_ITEMS]

    now = datetime.now(timezone.utc)
    last_build = format_datetime(now)

    # Build new RSS root
    rss = ET.Element('rss', attrib={'version': '2.0'})
    for prefix, uri in ns.items():
        rss.set(f'xmlns:{prefix}', uri)

    new_channel = ET.SubElement(rss, 'channel')

    ET.SubElement(new_channel, 'title').text = "SpaceNews (GitHub proxy)"
    ET.SubElement(new_channel, 'link').text = "https://spacenews.com/"
    ET.SubElement(new_channel, 'description').text = "Most recent SpaceNews articles proxied through GitHub for Protopage"
    ET.SubElement(new_channel, 'lastBuildDate').text = last_build
    ET.SubElement(new_channel, 'language').text = "en-US"

    # atom:link rel="self"
    ET.SubElement(new_channel, f"{{{ns['atom']}}}link", {
        'href': PROXY_FEED_URL,
        'rel': 'self',
        'type': 'application/rss+xml'
    })

    # Rebuild each item with clean fields
    for old in items:
        new_item = ET.SubElement(new_channel, 'item')

        title = old.find('title')
        link = old.find('link')
        desc = old.find('description')
        pub = old.find('pubDate')
        guid = old.find('guid')

        if title is not None and title.text:
            ET.SubElement(new_item, 'title').text = title.text
        if link is not None and link.text:
            ET.SubElement(new_item, 'link').text = link.text
        if desc is not None and desc.text:
            ET.SubElement(new_item, 'description').text = desc.text
        if pub is not None and pub.text:
            ET.SubElement(new_item, 'pubDate').text = pub.text
        if guid is not None and guid.text:
            g = ET.SubElement(new_item, 'guid')
            if 'isPermaLink' in guid.attrib:
                g.set('isPermaLink', guid.attrib['isPermaLink'])
            g.text = guid.text

        # Copy categories
        for cat in old.findall('category'):
            if cat.text:
                c = ET.SubElement(new_item, 'category')
                c.text = cat.text

        # dc:creator
        dc_creator = old.find('dc:creator', ns)
        if dc_creator is not None and dc_creator.text:
            ET.SubElement(new_item, f"{{{ns['dc']}}}creator").text = dc_creator.text

        # content:encoded (full HTML content)
        content_encoded = old.find('content:encoded', ns)
        if content_encoded is not None and content_encoded.text:
            ET.SubElement(new_item, f"{{{ns['content']}}}encoded").text = content_encoded.text

    xml_str = ET.tostring(rss, encoding='utf-8', xml_declaration=True).decode('utf-8')
    OUTPUT_FILE.write_text(xml_str, encoding='utf-8')

if __name__ == "__main__":
    main()
