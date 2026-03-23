from __future__ import annotations

import os
from typing import List, Dict
import feedparser

DEFAULT_FEEDS = [
    "https://www.rigzone.com/news/rss/rigzone_latest.aspx",
    "https://www.rigzone.com/news/rss/rigzone_original.aspx",
    "https://www.rigzone.com/news/rss/rigzone_headlines.aspx",
    "https://www.rigzone.com/news/rss/rigzone_exploration.aspx",
    "https://www.rigzone.com/news/rss/rigzone_production.aspx",
    "https://www.rigzone.com/news/rss/rigzone_finance.aspx",
    "https://www.rigzone.com/news/rss/rigzone_operations.aspx",
    "https://www.eia.gov/rss/todayinenergy.xml",
    "https://www.eia.gov/about/new/WNtest3.php",
    "https://www.eia.gov/rss/press_rss.xml",
    "https://www.eia.gov/petroleum/gasdiesel/includes/gas_diesel_rss.xml",
    "https://www.eia.gov/petroleum/heatingoilpropane/includes/hopu_rss.xml",
    "https://www.eia.gov/rss/testimony.xml",
    "https://www.eia.gov/rss/presentations.xml",
    "https://www.energy.gov/fecm/listings/fe-press-releases-and-techlines?view=rss",
    "https://www.energy.gov/fecm/listings/office-resource-sustainability-news?view=rss",
    "https://www.energy.gov/ceser/listings/petroleum-reserves-news?view=rss",
    "https://www.worldoil.com/rss?feed=news",
    "https://www.worldoil.com/rss?feed=topic%3Aoil+and+gas+prices",
    "https://www.worldoil.com/rss?feed=topic%3Alng",
    "https://www.worldoil.com/rss?feed=topic%3Amiddle+east",
    "https://news.google.com/rss/search?q=WTI+oil+OR+Brent+oil+OR+crude+oil+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=OPEC+OR+OPEC%2B+OR+oil+inventory+OR+EIA+crude+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Middle+East+oil+OR+Red+Sea+shipping+OR+Hormuz+OR+Iran+oil+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=CPI+OR+PMI+OR+GDP+OR+USD+OR+Fed+oil+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=natural+gas+OR+LNG+OR+energy+markets+when:1d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=refinery+outage+OR+pipeline+outage+OR+force+majeure+oil+when:3d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=SPR+OR+strategic+petroleum+reserve+oil+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Permian+OR+Bakken+OR+Eagle+Ford+OR+shale+oil+when:3d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=oil+tanker+OR+shipping+OR+freight+OR+VLCC+when:3d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=diesel+OR+gasoline+OR+distillate+OR+crack+spread+oil+when:3d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=China+oil+demand+OR+India+oil+demand+OR+jet+fuel+when:3d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Russia+oil+exports+OR+Ukraine+oil+OR+sanctions+oil+when:3d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=U.S.+oil+production+OR+rig+count+OR+drilling+activity+when:3d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Gulf+of+Mexico+oil+OR+hurricane+offshore+oil+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=Brent+spread+OR+WTI+spread+OR+backwardation+oil+when:3d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=oil+refinery+maintenance+OR+turnaround+when:7d&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=petrochemicals+OR+naphtha+OR+fuel+oil+energy+when:3d&hl=en-US&gl=US&ceid=US:en",
]


def get_feed_urls() -> List[str]:
    custom = os.getenv("RSS_FEEDS", "").strip()
    if not custom:
        return dedupe_urls(DEFAULT_FEEDS)
    normalized = custom.replace("\r", "\n").replace(",", "\n")
    return dedupe_urls([x.strip() for x in normalized.split("\n") if x.strip()])


def fetch_headlines(max_items_per_feed: int = 15) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for url in get_feed_urls():
        parsed = feedparser.parse(url)
        for entry in parsed.entries[:max_items_per_feed]:
            title = getattr(entry, "title", "") or ""
            summary = getattr(entry, "summary", "") or getattr(entry, "description", "") or ""
            link = getattr(entry, "link", "") or ""
            published = getattr(entry, "published", "") or getattr(entry, "updated", "") or ""
            source = url
            items.append(
                {
                    "id": make_id(title, link),
                    "title": title,
                    "summary": summary,
                    "link": link,
                    "published": published,
                    "source": source,
                }
            )
    return dedupe_items(items)


def make_id(title: str, link: str) -> str:
    return f"{title.strip().lower()}|{link.strip().lower()}"


def dedupe_items(items: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen = set()
    out = []
    for item in items:
        key = item["id"]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def dedupe_urls(urls: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for url in urls:
        if url in seen:
            continue
        seen.add(url)
        out.append(url)
    return out
