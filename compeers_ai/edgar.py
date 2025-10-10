import requests
from bs4 import BeautifulSoup
from datetime import datetime
from .parsers import find_market_numbers
from .models import MarketMetrics, Citation

USER_AGENT = "CompeersAI Bot"

def edgar_search(company: str, count=20):
    url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={company}&type=10-K&count={count}&output=atom"
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(url, headers=headers)
    soup = BeautifulSoup(r.text, "xml")
    entries = []
    for e in soup.find_all("entry"):
        entries.append({
            "title": e.title.text,
            "link": e.link["href"],
            "updated": e.updated.text
        })
    return entries

def harvest_edgar(company: str):
    filings = edgar_search(company)
    metrics, citations = [], []
    for f in filings:
        txt = requests.get(f["link"], headers={"User-Agent": USER_AGENT}).text
        history, total, cur, cagr = find_market_numbers(txt)
        if total or history:
            m = MarketMetrics(source_id=f["title"], total_market_size=total, currency=cur, history=history, cagr=cagr)
            c = Citation(source_id=f["title"], source_type="edgar", url_or_path=f["link"], excerpt=txt[:800], access_date=datetime.utcnow().isoformat())
            metrics.append(m); citations.append(c)
    return metrics, citations
