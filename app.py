import streamlit as st
import pandas as pd
import re
import tldextract
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pathlib import Path
import tempfile
import numpy as np
import datetime

# pytrends (optional, handle rate limits)
try:
    from pytrends.request import TrendReq
    PYTRENDS_AVAILABLE = True
except Exception:
    TrendReq = None
    PYTRENDS_AVAILABLE = False

# Backend import
from compeers_ai.harvester import run_harvest

# ---------------- API KEYS ----------------
API_KEY = st.secrets.get("GOOGLE_API_KEY", "")
CSE_ID = st.secrets.get("GOOGLE_CSE_ID", "")

# --- STREAMLIT CONFIG ---
st.set_page_config(page_title="COMPEER'S AI", layout="wide")
st.markdown("<h1 style='text-align: center;'>COMPEER'S AI</h1>", unsafe_allow_html=True)
st.caption("Auto-Discovery, Shortlisting & Market Intelligence")
st.divider()

# ---------------- Sidebar ----------------
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", [
    "Source Discovery", "Market Metrics", "Search Interest", "Competitor Landscape"
])

# ---------------- Helpers ----------------
def google_search_raw(q, api_key, cse_id, total_num_results):
    service = build("customsearch", "v1", developerKey=api_key)
    all_items = []
    total_to_fetch = min(total_num_results, 100)
    for start_index in range(1, total_to_fetch + 1, 10):
        try:
            resp = service.cse().list(q=q, cx=cse_id, num=10, start=start_index).execute()
            current_items = resp.get("items", [])
            all_items.extend(current_items)
            if len(all_items) >= total_num_results or not current_items:
                all_items = all_items[:total_num_results]
                break
        except Exception as e:
            raise e
    return all_items

PAYWALLED = {"nytimes.com", "wsj.com", "ft.com", "economist.com"}

def infer_publisher_and_type(url, title, snippet):
    ext = tldextract.extract(url)
    domain = ".".join(part for part in (ext.domain, ext.suffix) if part)
    publisher = domain if domain else url
    low = (domain or "").lower()
    src_type = "Other"
    if any(x in low for x in ("amazon","flipkart","walmart","alibaba","etsy")):
        src_type = "E-commerce"
    elif any(x in low for x in ("wikipedia","edu")):
        src_type = "Academic"
    elif any(x in low for x in ("medium","blogspot","wordpress","substack","blog")):
        src_type = "Blog"
    elif any(x in low for x in ("news","guardian","reuters","bbc","economictimes","thehindu")):
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
    match = re.search(r"(19|20)\d{2}", text)
    return match.group(0) if match else ""

# =========================================================
#  PAGE 1: SOURCE DISCOVERY
# =========================================================
if page == "Source Discovery":
    if 'short_df' not in st.session_state:
        st.session_state['short_df'] = None

    st.subheader("1. Define Search Parameters")
    cat = st.text_input("Category / Topic (e.g., Men's Face Wash Market)")
    hint = st.text_input("Refinement Keywords (comma-separated, optional)")
    num_results = st.slider("Number of Search Results to Retrieve", 5, 100, 20)

    if st.button("2. Run Auto-Discovery and Classify Sources", type="primary", use_container_width=True):
        if not API_KEY or not CSE_ID:
            st.error("API KEYS NOT FOUND. Please add GOOGLE_API_KEY & GOOGLE_CSE_ID in Streamlit secrets.")
            st.session_state['short_df'] = None
        elif not cat.strip():
            st.warning("Enter a category/topic to run the search.")
        else:
            query = cat.strip()
            if hint.strip():
                query += " " + " ".join([h.strip() for h in hint.split(",") if h.strip()])
            try:
                items = google_search_raw(query, API_KEY, CSE_ID, num_results)
            except Exception as e:
                st.error(f"Search failed: {e}")
                items = []

            if not items:
                st.warning("No search results found.")
            else:
                rows = []
                for it in items:
                    title, link, snippet = it.get("title",""), it.get("link",""), it.get("snippet","")
                    publisher, src_type, access = infer_publisher_and_type(link, title, snippet)
                    coverage = extract_year(title + " " + snippet) or ""
                    relevance_note = (snippet[:200] + "...") if snippet and len(snippet)>200 else snippet
                    rows.append({
                        "source_type": src_type,
                        "title": title,
                        "publisher": publisher,
                        "coverage_period": coverage,
                        "access_type": access,
                        "url": link,
                        "relevance_note": relevance_note
                    })
                st.session_state['short_df'] = pd.DataFrame(rows)

    if st.session_state['short_df'] is not None:
        st.subheader("3. Auto-Discovered Source Shortlist")
        st.dataframe(st.session_state['short_df'].reset_index(drop=True), use_container_width=True)

# =========================================================
#  PAGE 2: MARKET METRICS
# =========================================================
elif page == "Market Metrics":
    st.subheader("📂 Upload Market Reports & Fetch SEC Filings")
    uploaded_files = st.file_uploader("Upload Reports", type=["pdf","csv","xls","xlsx"], accept_multiple_files=True)
    company = st.text_input("Company name for SEC EDGAR filings (optional)")

    if st.button("🚀 Run Market Harvest", use_container_width=True):
        if not uploaded_files and not company:
            st.warning("Upload at least one report or enter a company.")
        else:
            tmpdir = Path(tempfile.mkdtemp())
            for uf in uploaded_files:
                with open(tmpdir/uf.name, "wb") as f:
                    f.write(uf.getbuffer())
            dfm, dfc = run_harvest(upload_dir=tmpdir, company=company, outdir=tmpdir/"outputs")
            st.success("✅ Harvest completed!")
            st.dataframe(dfm); st.dataframe(dfc)

# =========================================================
#  PAGE 3: SEARCH INTEREST
# =========================================================
elif page == "Search Interest":
    st.subheader("📊 Search Interest Trends")
    topic = st.text_input("Enter Topic/Keyword", placeholder="e.g., Baby Food")
    geo = st.text_input("Region (country code)", value="IN")
    timeframe = st.selectbox("Timeframe", ["today 12-m","today 5-y","all","demo mode"])

    if st.button("Fetch Trends"):
        if not topic.strip():
            st.warning("Enter a topic.")
        else:
            use_demo = timeframe=="demo mode" or not PYTRENDS_AVAILABLE
            if not use_demo:
                try:
                    pytrends = TrendReq(hl='en-US', tz=330)
                    tf = "today 12-m" if timeframe=="today 12-m" else ("today 5-y" if timeframe=="today 5-y" else "all")
                    pytrends.build_payload([topic], timeframe=tf, geo=geo)
                    df_trends = pytrends.interest_over_time()
                    if df_trends.empty: use_demo=True
                except Exception as e:
                    st.warning(f"Trends failed: {e} → demo mode used")
                    use_demo=True
            if use_demo:
                dates = pd.date_range(end=datetime.date.today(), periods=12, freq="M")
                values = np.random.randint(10,100,len(dates))
                df_trends = pd.DataFrame({topic:values}, index=dates)

            st.line_chart(df_trends)

# =========================================================
#  PAGE 4: COMPETITOR LANDSCAPE
# =========================================================
elif page == "Competitor Landscape":
    st.subheader("🏆 Competitor Landscape")
    uploaded_file = st.file_uploader("Upload Competitor Data", type=["csv","xlsx"])
    competitors_text = st.text_area("Or Enter Competitor Names", placeholder="HUL, P&G, Dabur")
    rubric = st.selectbox("Choose rubric", ["None","MOVI","SWOT","Custom"])

    if st.button("Run Competitor Analysis"):
        if uploaded_file:
            df_comp = pd.read_csv(uploaded_file) if uploaded_file.name.endswith(".csv") else pd.read_excel(uploaded_file)
        elif competitors_text.strip():
            df_comp = pd.DataFrame({"Competitor":[c.strip() for c in competitors_text.split(",")]})
        else:
            df_comp = pd.DataFrame()

        if df_comp.empty:
            st.warning("No competitor data.")
        else:
            if rubric=="MOVI":
                df_comp["Market Share"] = ["High","Medium","Low"]*10
                df_comp["Offering"] = ["Premium","Mass","Niche"]*10
                df_comp["Value Proposition"] = ["Quality","Price","Reach"]*10
                df_comp["Innovation"] = ["Strong","Moderate","Weak"]*10
            elif rubric=="SWOT":
                df_comp["Strength"] = ["Brand","Distribution","R&D"]*10
                df_comp["Weakness"] = ["Price","Portfolio gap","Quality"]*10
                df_comp["Opportunity"] = ["Channel expansion","New segment","Premiumization"]*10
                df_comp["Threat"] = ["Regulation","Entrants","Raw materials"]*10
            st.dataframe(df_comp)
            st.download_button("⬇️ Download CSV", df_comp.to_csv(index=False).encode("utf-8"), file_name="competitor_analysis.csv")
