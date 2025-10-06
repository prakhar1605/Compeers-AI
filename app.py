# app.py
import os
import csv
import re
import hashlib
import datetime

import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
import tldextract

# try to load .env locally, but fail silently on deploy if python-dotenv isn't installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv not available — that's OK on Streamlit Cloud where we'll use st.secrets
    pass

# ----------------------
# Basic page config
# ----------------------
st.set_page_config(page_title="COMPEER'S AI", layout="centered")
st.title("COMPEER'S AI")

# ----------------------
# Helper: robust secret loader (hybrid)
# ----------------------
def get_key(name: str):
    """
    Priority:
      1. environment variable (os.getenv)
      2. streamlit secrets (st.secrets) — wrapped in try/except so local runs without secrets.toml won't crash
      3. None if not found
    """
    # 1) env var
    val = os.getenv(name)
    if val:
        return val

    # 2) streamlit secrets (safe)
    try:
        # use .get to avoid raising on missing key
        if hasattr(st, "secrets"):
            # st.secrets.get may raise if secrets parsing fails; wrap in try
            try:
                s = st.secrets.get(name)
                if s:
                    return s
            except Exception:
                # fallback to indexing only inside its own try
                try:
                    if name in st.secrets:
                        return st.secrets[name]
                except Exception:
                    pass
    except Exception:
        pass

    return None


API_KEY = get_key("GOOGLE_API_KEY")
CSE_ID = get_key("GOOGLE_CSE_ID")

# ----------------------
# Inform user if keys missing (don't show key values)
# ----------------------
if not API_KEY or not CSE_ID:
    st.warning(
        "API keys not found. Locally: put keys in a `.env` file or set environment variables.\n"
        "On Streamlit Cloud: go to Settings → Secrets and add `GOOGLE_API_KEY` and `GOOGLE_CSE_ID`."
    )

# ---------------------------
# Google CSE wrapper
# ---------------------------
def google_search_raw(q, api_key, cse_id, num=10):
    # returns list of result items from Google Custom Search
    service = build("customsearch", "v1", developerKey=api_key)
    resp = service.cse().list(q=q, cx=cse_id, num=num).execute()
    return resp.get("items", [])

# ---------------------------
# Source inference utilities
# ---------------------------
PAYWALLED = {"nytimes.com", "wsj.com", "ft.com", "economist.com"}

def infer_publisher_and_type(url, title, snippet):
    ext = tldextract.extract(url or "")
    domain = ".".join(part for part in (ext.domain, ext.suffix) if part)
    publisher = domain if domain else (url or "")
    low = (domain or "").lower()
    src_type = "Other"

    if any(x in low for x in ("amazon","flipkart","walmart","alibaba","etsy")):
        src_type = "E-commerce"
    elif any(x in low for x in ("wikipedia","edu")):
        src_type = "Academic"
    elif any(x in low for x in ("medium","blogspot","wordpress","substack","blog")):
        src_type = "Blog"
    elif any(x in low for x in ("news","nytimes","guardian","reuters","bbc","thehindu","economictimes")):
        src_type = "News"
    elif any(x in low for x in ("gov","who.int","un.org")):
        src_type = "Official"
    else:
        combined = (title or "") + " " + (snippet or "")
        if re.search(r"\b(review|buy|price|shop|discount|sale)\b", combined, re.I):
            src_type = "E-commerce"
        elif re.search(r"\b(study|journal|research|doi|pdf)\b", combined, re.I):
            src_type = "Academic"
        else:
            src_type = "Vendor/Other"

    access = "Paywalled" if domain in PAYWALLED else "Free"
    return publisher, src_type, access

def extract_year(text):
    match = re.search(r"(19|20)\d{2}", text or "")
    return match.group(0) if match else ""

# ---------------------------
# Registry: append approved sources for traceability
# ---------------------------
REGISTRY_PATH = "source_registry.csv"

def make_checksum(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()

def append_to_registry(rows, parser="google_cse_v1", reliability="unknown"):
    """
    rows: list of dicts with at least keys:
      title, publisher, source_type, access_type, coverage_period, relevance_note, url
    Appends rows to REGISTRY_PATH with access_date, parser, parser_version, reliability_flag, checksum.
    """
    now = datetime.datetime.utcnow().isoformat()
    header = [
        "url","title","publisher","source_type","access_type","coverage_period",
        "relevance_note","access_date","parser","parser_version","reliability_flag","checksum","rows_parsed"
    ]
    exists = os.path.exists(REGISTRY_PATH)
    try:
        with open(REGISTRY_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            if not exists:
                writer.writeheader()
            for r in rows:
                url = r.get("url","")
                title = r.get("title","")
                relevance_note = r.get("relevance_note","")
                text_blob = f"{title} {relevance_note} {url}"
                writer.writerow({
                    "url": url,
                    "title": title,
                    "publisher": r.get("publisher",""),
                    "source_type": r.get("source_type",""),
                    "access_type": r.get("access_type",""),
                    "coverage_period": r.get("coverage_period",""),
                    "relevance_note": relevance_note,
                    "access_date": now,
                    "parser": parser,
                    "parser_version": "1.0",
                    "reliability_flag": reliability,
                    "checksum": make_checksum(text_blob),
                    "rows_parsed": 1
                })
        return True, None
    except Exception as e:
        return False, str(e)

# ----------------------
# UI inputs
# ----------------------
cat = st.text_input("Category / Topic")
hint = st.text_input("Hints (comma-separated, optional)")
num_results = st.slider("Number of search results", min_value=5, max_value=20, value=10)

st.markdown("---")
st.write("Note: Add API keys in `.env` (local) or Streamlit Secrets (deploy).")

# show current key status (NOT the key itself) for debugging
if API_KEY and CSE_ID:
    st.success("API key and CSE ID found — search should work.")
else:
    st.info("API key or CSE ID missing — search won't run until provided.")

# initialize session shortlist
if "shortlist" not in st.session_state:
    st.session_state.shortlist = None

# ----------------------
# Run auto-discovery
# ----------------------
if st.button("Run auto-discovery"):
    # basic validation
    if not API_KEY or not CSE_ID:
        st.error("API_KEY or CSE_ID not set. Set them in .env (local) or in Streamlit Secrets (deploy).")
    elif not cat or not cat.strip():
        st.warning("Enter a category/topic.")
    else:
        query = cat.strip()
        if hint and hint.strip():
            query += " " + " ".join([h.strip() for h in hint.split(",") if h.strip()])

        try:
            items = google_search_raw(query, API_KEY, CSE_ID, num=num_results)
        except Exception as e:
            st.error(f"Search failed: {e}")
            items = []

        if not items:
            st.warning("No search results.")
            st.session_state.shortlist = None
        else:
            rows = []
            for it in items:
                title = it.get("title", "")
                link = it.get("link", "")
                snippet = it.get("snippet", "")
                publisher, src_type, access = infer_publisher_and_type(link, title, snippet)
                coverage = extract_year(title + " " + snippet) or ""
                relevance_note = (snippet[:200] + "...") if snippet and len(snippet) > 200 else (snippet or "")
                rows.append({
                    "source_type": src_type,
                    "title": title,
                    "publisher": publisher,
                    "coverage_period": coverage,
                    "access_type": access,
                    "url": link,
                    "relevance_note": relevance_note
                })

            short_df = pd.DataFrame(rows)
            st.subheader("Auto-discovered shortlist")
            st.dataframe(short_df.reset_index(drop=True))

            # persist shortlist in session state
            st.session_state.shortlist = short_df.to_dict(orient="records")

# ---------------------------
# If shortlist exists, render checkboxes and finalize
# ---------------------------
if st.session_state.get("shortlist"):
    shortlist = st.session_state.shortlist
    st.markdown("### Select sources you want to approve")
    approved = []
    # render checkboxes preserving state values
    for i, r in enumerate(shortlist):
        key = f"sel_{i}"
        default_val = st.session_state.get(key, False)
        label = f"[{r.get('source_type')}] {r.get('title')} — {r.get('publisher')}"
        checked = st.checkbox(label, key=key, value=default_val)
        if checked:
            approved.append(r)

    if st.button("Finalize shortlist"):
        if not approved:
            st.warning("Select at least one item.")
        else:
            final_df = pd.DataFrame(approved)

            # candidate phrases (simple heuristic)
            candidate_phrases = []
            for txt in (final_df['title'].astype(str) + " " + final_df['relevance_note'].astype(str)):
                tokens = re.findall(r"\b[A-Za-z]{4,}\b", txt)
                candidate_phrases.extend([t.lower() for t in tokens])
            freq = pd.Series(candidate_phrases).value_counts()
            suggestions = list(freq.head(8).index) if not freq.empty else []
            suggested_normalized = f"{suggestions[0].title()}" if suggestions else cat.strip().title()
            if len(suggestions) > 1:
                suggested_normalized += f" > {suggestions[1].title()}"

            # append to registry (optional)
            ok, err = append_to_registry(approved, parser="google_cse_v1", reliability="manual_approval")
            if ok:
                st.success("Final shortlist ready ✅ and saved to source_registry.csv")
            else:
                st.warning(f"Final shortlist ready ✅ but failed to save registry: {err}")

            st.subheader("Final Shortlist")
            st.dataframe(final_df.reset_index(drop=True))
            st.markdown("#### Suggested normalized category")
            st.info(suggested_normalized)

            csv_bytes = final_df.to_csv(index=False).encode('utf-8')
            st.download_button("Download Shortlist CSV", csv_bytes, file_name="whi_shortlist.csv")

            mapping_df = pd.DataFrame([{"original_query": cat.strip(), "suggested_normalized": suggested_normalized}])
            st.download_button("Download mapping CSV", mapping_df.to_csv(index=False).encode('utf-8'),
                               file_name="whi_suggested_mapping.csv")
