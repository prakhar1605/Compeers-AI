from pathlib import Path
import pandas as pd
import json
from .parsers import parse_provider_file
from .edgar import harvest_edgar

def harvest_from_uploads(upload_dir: Path):
    metrics, citations = [], []
    for f in Path(upload_dir).iterdir():
        if f.is_file():
            m, c = parse_provider_file(f)
            if m:
                metrics.append(m); citations.extend(c)
    return metrics, citations

def run_harvest(upload_dir="uploads", company=None, outdir="outputs"):
    Path(outdir).mkdir(parents=True, exist_ok=True)
    metrics, citations = harvest_from_uploads(Path(upload_dir))
    if company:
        m2, c2 = harvest_edgar(company)
        metrics.extend(m2); citations.extend(c2)
    # save csv/json
    dfm = pd.DataFrame([m.to_dict() for m in metrics])
    dfc = pd.DataFrame([c.to_dict() for c in citations])
    dfm.to_csv(Path(outdir)/"market_metrics.csv", index=False)
    dfc.to_csv(Path(outdir)/"citations.csv", index=False)
    dfm.to_json(Path(outdir)/"market_metrics.json", orient="records", indent=2)
    dfc.to_json(Path(outdir)/"citations.json", orient="records", indent=2)
    return dfm, dfc
