# SN-Feed — SpaceNews for Protopage

SpaceNews still publishes `https://spacenews.com/feed`, but that official RSS is **not** the current news desk. It lags the homepage by days and is mostly press releases.

This repo rebuilds a clean RSS 2.0 file from the public WordPress REST API:

`https://spacenews.com/wp-json/wp/v2/posts`

That endpoint is current. Protopage can subscribe to the rebuilt file.

## Feed URL for Protopage

```
https://jduggan13-dev.github.io/SN-Feed/feed.xml
```

### Add or refresh the widget

1. Replace `update_spacenews_feed.py` in this repo with the new script.
2. Commit and push to `main`.
3. GitHub → **Actions** → **Update SpaceNews feed** → **Run workflow**.
4. Confirm `feed.xml` now starts with today's headlines, not last week's press releases.
5. In Protopage:
   - If the widget already points at the URL above, open the widget settings and refresh / re-paste the same URL. Protopage caches aggressively; deleting the widget and adding it again is the reliable fix.
   - If you are adding it fresh: **Add widgets** → news feed → paste the URL → Go → drag onto the page.

Do **not** point Protopage at `https://spacenews.com/feed`. That is the broken source.

## What the Action does

`.github/workflows/update-feed.yml` already runs hourly and on manual dispatch. No workflow change is required unless you want a tighter schedule (`*/30 * * * *`).

## Backup feeds that actually update

Keep SpaceNews as the main widget. Add these as extra Protopage news widgets if you want coverage when SpaceNews is quiet:

| Source | RSS URL |
| --- | --- |
| Spaceflight Now | `https://spaceflightnow.com/feed/` |
| Space.com | `https://www.space.com/feeds.xml` |
| NASA breaking news | `https://www.nasa.gov/rss/dyn/breaking_news.rss` |
| The Space Review | `https://www.thespacereview.com/articles.xml` |

If you later want a second reader that is not Protopage, Inoreader / Feedly / NewsBlur all accept the same `feed.xml` URL.
