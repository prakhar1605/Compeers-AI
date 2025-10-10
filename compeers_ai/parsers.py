from pathlib import Path
import pandas as pd
import pdfplumber
import re
from datetime import datetime
from .utils import safe_parse_float, detect_currency, compute_cagr
from .models import MarketMetrics, Citation

def extract_text_from_pdf(path: Path) -> str:
    text = []
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text.append(t)
    return "\n".join(text)

def find_market_numbers(text: str):
    history = {}
    pairs = re.findall(r"(20\d{2})[^0-9]{0,5}([\d,\.]+)", text)
    for year, val in pairs:
        try:
            history[int(year)] = safe_parse_float(val)
        except:
            continue
    total = None
    m = re.search(r"market size.*?([\d,\.]+)", text, flags=re.I)
    if m:
        total = safe_parse_float(m.group(1))
    cur = detect_currency(text)
    cagr = compute_cagr(history) if history else None
    return history, total, cur, cagr

def parse_provider_file(path: Path):
    text = ""
    if path.suffix.lower() in [".csv", ".xls", ".xlsx"]:
        try:
            df = pd.read_csv(path) if path.suffix.lower()==".csv" else pd.read_excel(path)
            text = " ".join(df.astype(str).fillna("").head(50).to_string().split())
        except:
            pass
    elif path.suffix.lower() == ".pdf":
        text = extract_text_from_pdf(path)

    if text:
        history, total, cur, cagr = find_market_numbers(text)
        metrics = MarketMetrics(source_id=path.name, total_market_size=total, currency=cur, history=history, cagr=cagr)
        citation = Citation(source_id=path.name, source_type="upload", url_or_path=str(path), excerpt=text[:500], access_date=datetime.utcnow().isoformat())
        return metrics, [citation]
    return None, []
