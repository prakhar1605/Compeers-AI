from dataclasses import dataclass, asdict
from typing import Dict, Optional

@dataclass
class Citation:
    source_id: str
    source_type: str
    url_or_path: str
    excerpt: str
    access_date: str
    confidence: float = 0.7

    def to_dict(self):
        return asdict(self)

@dataclass
class MarketMetrics:
    source_id: str
    total_market_size: Optional[float] = None
    currency: Optional[str] = None
    period_start: Optional[int] = None
    period_end: Optional[int] = None
    history: Optional[Dict[int, float]] = None
    cagr: Optional[float] = None
    subcategory_splits: Optional[Dict[str, float]] = None
    channel_splits: Optional[Dict[str, float]] = None
    notes: Optional[str] = None

    def to_dict(self):
        d = asdict(self)
        if isinstance(self.history, dict):
            d['history'] = {str(k): v for k, v in self.history.items()}
        return d
