"""arXiv resmi Atom API: en güncel AI ve makine öğrenimi makaleleri."""

from newsletter.models import NewsItem
from newsletter.sources.feeds import clean, entry_date, fetch_feed

URL = ("https://export.arxiv.org/api/query?search_query=cat:cs.AI+OR+cat:cs.LG"
       "&sortBy=submittedDate&sortOrder=descending&max_results=8")


def fetch():
    return [
        NewsItem(
            source="arXiv",
            title=entry.title.replace("\n", " ").strip(),
            date=entry_date(entry),
            link=entry.link,
            summary=clean(entry.summary, 400),
        )
        for entry in fetch_feed(URL).entries
    ]
