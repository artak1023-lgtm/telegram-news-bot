import pytz

DEFAULT_SOURCES = {
    "BBC": "https://feeds.bbci.co.uk/news/world/rss.xml",
    "Reuters": "https://feeds.reuters.com/reuters/worldNews",
    "Al Jazeera": "https://www.aljazeera.com/xml/rss/all.xml",
}

DEFAULT_KEYWORDS = [
    "armenia", "azerbaijan", "war", "conflict",
    "iran", "russia", "usa", "europe", "turkey"
]

CHECK_INTERVAL = 60  # 1 minute (fixed)
AM_TZ = pytz.timezone("Asia/Yerevan")
US_TZ = pytz.timezone("America/New_York")
