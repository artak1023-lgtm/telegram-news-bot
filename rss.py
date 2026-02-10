import feedparser
from dateutil import parser
from config import AM_TZ, US_TZ

def parse_feed(url):
    feed = feedparser.parse(url)
    items = []

    for entry in feed.entries[:10]:
        title = entry.get("title", "")
        link = entry.get("link", "")
        published = entry.get("published", "")

        try:
            dt = parser.parse(published)
            us_time = dt.astimezone(US_TZ).strftime("%H:%M")
            am_time = dt.astimezone(AM_TZ).strftime("%H:%M")
        except:
            us_time = am_time = "?"

        items.append({
            "title": title,
            "link": link,
            "us_time": us_time,
            "am_time": am_time,
            "id": f"{title}_{link}"
        })

    return items
