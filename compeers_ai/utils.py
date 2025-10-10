import re
from typing import Optional, Dict

def safe_parse_float(s: Optional[str]) -> Optional[float]:
    """Convert string with $, commas, million/billion notation into float."""
    if s is None:
        return None
    if isinstance(s, (int, float)):
        return float(s)

    s2 = str(s).lower().replace(",", "").strip()
    try:
        if "billion" in s2 or "bn" in s2:
            return float(re.findall(r"[\d\.]+", s2)[0]) * 1e9
        elif "million" in s2 or "m" in s2:
            return float(re.findall(r"[\d\.]+", s2)[0]) * 1e6
        else:
            return float(re.findall(r"[-+]?\d*\.?\d+", s2)[0])
    except Exception:
        return None

def detect_currency(text: str) -> Optional[str]:
    """Detect common currency from text string."""
    if not text:
        return None
    if "$" in text or "usd" in text.lower():
        return "USD"
    if "€" in text or "eur" in text.lower():
        return "EUR"
    if "£" in text or "gbp" in text.lower():
        return "GBP"
    if "₹" in text or "inr" in text.lower():
        return "INR"
    return None

def compute_cagr(history: Dict[int, float]) -> Optional[float]:
    """Compute CAGR from history dictionary {year: value}."""
    if not history or len(history) < 2:
        return None
    years = sorted(history.keys())
    start, end = years[0], years[-1]
    vs, ve = history[start], history[end]
    if not vs or vs <= 0:
        return None
    n = end - start
    try:
        return (ve / vs) ** (1.0 / n) - 1.0
    except Exception:
        return None
