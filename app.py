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
import itertools

# pytrends optional import
try:
    from pytrends.request import TrendReq
    PYTRENDS_AVAILABLE = True
except Exception:
    TrendReq = None
    PYTRENDS_AVAILABLE = False

# Backend import
from compeers_ai.harvester import run_harvest

# ---------------- API KEYS (from Streamlit secrets) ----------------
API_KEY = st.secrets.get("GOOGLE_API_KEY", "")
CSE_ID = st.secrets.get("GOOGLE_CSE_ID", "")

# --- STREAMLIT CONFIG ---
st.set_page_config(page_title="COMPEER'S AI", layout="wide")
st.markdown("<h1 style='text-align: center;'>COMPEER'S AI</h1>", unsafe_allow_html=True)
st.caption("Auto-Discovery, Shortlisting & Market Intelligence")
st.divider()

# ---------------- Sidebar Navigation ----------------
st.sidebar.title("Navigation")
page = st.sidebar.radio("Go to", ["Source Discovery", "Market Metrics", "Search Interest", "Competitor Landscape"])

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
        except HttpError as e:
            raise e
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
    num_results = st.slider("Number of Search Results to Retrieve", min_value=5, max_value=100, value=20)

    if st.button("2. Run Auto-Discovery and Classify Sources", type="primary", use_container_width=True):
        if not API_KEY or not CSE_ID:
            st.error("API KEYS NOT FOUND. Please set GOOGLE_API_KEY and GOOGLE_CSE_ID in Streamlit secrets.")
            st.session_state['short_df'] = None
        elif not cat.strip():
            st.warning("Enter a category/topic to run the search.")
            st.session_state['short_df'] = None
        else:
            query = cat.strip()
            if hint.strip():
                query += " " + " ".join([h.strip() for h in hint.split(",") if h.strip()])

            with st.spinner('Searching the web and classifying sources...'):
                try:
                    items = google_search_raw(query, API_KEY, CSE_ID, num_results)
                except Exception as e:
                    st.error(f"Search failed: {e}")
                    items = []

            if not items:
                st.warning("No search results found.")
                st.session_state['short_df'] = None
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
                st.session_state['short_df'] = pd.DataFrame(rows)

    if st.session_state['short_df'] is not None:
        short_df = st.session_state['short_df']
        st.subheader("3. Auto-Discovered Source Shortlist")
        st.dataframe(short_df.reset_index(drop=True), use_container_width=True)

        approved = []
        st.markdown("---")
        st.subheader("4. Select Sources for Final Approval")

        col1, col2 = st.columns([0.05, 0.95])
        for i, r in short_df.iterrows():
            key = f"sel_{i}"
            with col1:
                checked = st.checkbox("", key=key)
            with col2:
                st.write(f"**[{r['source_type']}]** {r['title']} *— {r['publisher']}*")
            if checked:
                approved.append(r)

        st.markdown("---")
        if st.button("5. Finalize Shortlist and Generate Category Data", type="secondary", use_container_width=True):
            if not approved:
                st.warning("Select at least one item before finalizing.")
            else:
                final_df = pd.DataFrame(approved)
                candidate_phrases = []
                for txt in (final_df['title'].astype(str) + " " + final_df['relevance_note'].astype(str)):
                    tokens = re.findall(r"\b[A-Za-z]{4,}\b", txt)
                    candidate_phrases.extend([t.lower() for t in tokens])
                freq = pd.Series(candidate_phrases).value_counts()
                suggestions = list(freq.head(8).index) if not freq.empty else []
                suggested_normalized = f"{suggestions[0].title()}" if suggestions else cat.strip().title()
                if len(suggestions) > 1:
                    suggested_normalized += f" > {suggestions[1].title()}"

                st.success("Shortlist finalized.")
                st.subheader("Final Approved Shortlist")
                st.dataframe(final_df.reset_index(drop=True), use_container_width=True)
                st.subheader("Suggested Normalized Category")
                st.code(suggested_normalized)

                col_dl1, col_dl2 = st.columns(2)
                col_dl1.download_button("Download Shortlist CSV", final_df.to_csv(index=False).encode('utf-8'),
                                        file_name="compeers_shortlist.csv", use_container_width=True)
                mapping_df = pd.DataFrame([{"original_query": cat.strip(), "suggested_normalized": suggested_normalized}])
                col_dl2.download_button("Download Mapping CSV", mapping_df.to_csv(index=False).encode('utf-8'),
                                        file_name="compeers_suggested_mapping.csv", use_container_width=True)

# =========================================================
#  PAGE 2: MARKET METRICS
# =========================================================
elif page == "Market Metrics":
    st.subheader("📂 Upload Market Reports & Fetch SEC Filings")
    uploaded_files = st.file_uploader("Upload NIQ / Circana / Euromonitor reports",
                                      type=["pdf","csv","xls","xlsx"],
                                      accept_multiple_files=True)
    company = st.text_input("Company name for SEC EDGAR filings (optional)", placeholder="e.g., Procter & Gamble")

    if st.button("🚀 Run Market Harvest", use_container_width=True):
        if not uploaded_files and not company:
            st.warning("Please upload at least one report or enter a company.")
        else:
            with st.spinner("Extracting market data..."):
                tmpdir = Path(tempfile.mkdtemp())
                for uf in uploaded_files:
                    path = tmpdir / uf.name
                    with open(path, "wb") as f:
                        f.write(uf.getbuffer())
                dfm, dfc = run_harvest(upload_dir=tmpdir, company=company, outdir=tmpdir/"outputs")
            st.success("✅ Harvest completed!")
            st.subheader("📈 Market Metrics")
            st.dataframe(dfm, use_container_width=True)
            st.subheader("🔗 Citations")
            st.dataframe(dfc, use_container_width=True)
            st.download_button("⬇️ Download Market Metrics CSV", dfm.to_csv(index=False).encode("utf-8"), file_name="market_metrics.csv")
            st.download_button("⬇️ Download Citations CSV", dfc.to_csv(index=False).encode("utf-8"), file_name="citations.csv")

# =========================================================
#  PAGE 3: SEARCH INTEREST
# =========================================================
elif page == "Search Interest":
    st.subheader("📊 Search Interest Trends")
    topic = st.text_input("Enter Topic/Keyword", placeholder="e.g., Baby Food, Men's Grooming")
    geo = st.text_input("Region (country code, e.g., IN, US, or leave blank for Worldwide)", value="IN")
    timeframe = st.selectbox("Timeframe", ["today 12-m", "today 5-y", "all", "demo mode"])

    if st.button("Fetch Google Trends Data", use_container_width=True):
        if not topic.strip():
            st.warning("Please enter a topic or keyword.")
        else:
            with st.spinner("Fetching data..."):
                use_demo = False
                if timeframe == "demo mode" or not PYTRENDS_AVAILABLE:
                    use_demo = True
                if not use_demo:
                    try:
                        pytrends = TrendReq(hl='en-US', tz=330)
                        tf = "today 12-m" if timeframe == "today 12-m" else ("today 5-y" if timeframe == "today 5-y" else "all")
                        pytrends.build_payload([topic], timeframe=tf, geo=geo)
                        df_trends = pytrends.interest_over_time()
                        if df_trends is None or df_trends.empty:
                            use_demo = True
                    except Exception as e:
                        st.warning(f"Google Trends failed: {e} — using demo data.")
                        use_demo = True
                if use_demo:
                    months = 60 if timeframe == "today 5-y" else 12
                    end = datetime.date.today()
                    dates = pd.date_range(end=end, periods=months, freq="M")
                    values = np.clip(np.round(np.random.normal(loc=55, scale=18, size=len(dates))).astype(int), 1, 100)
                    df_trends = pd.DataFrame({topic: values}, index=dates)
                    df_trends.index.name = "date"
                st.subheader("📈 Interest Over Time")
                st.line_chart(df_trends[topic] if topic in df_trends.columns else df_trends)
                st.download_button("⬇️ Download Trends CSV", df_trends.reset_index().to_csv(index=False).encode("utf-8"), file_name=f"{topic}_trends.csv")
                df_related_demo = pd.DataFrame({"query": [f"{topic} benefits", f"{topic} price", f"best {topic} 2025"], "value": [95, 80, 65]})
                st.subheader("🔎 Related Queries (Demo)")
                st.dataframe(df_related_demo, use_container_width=True)
                st.download_button("⬇️ Download Related Queries CSV", df_related_demo.to_csv(index=False).encode("utf-8"), file_name=f"{topic}_related_queries.csv")

# =========================================================
#  PAGE 4: COMPETITOR LANDSCAPE
# =========================================================
elif page == "Competitor Landscape":
    st.subheader("🏆 Competitor Landscape")
    uploaded_file = st.file_uploader("Upload Competitor Data (CSV/XLSX)", type=["csv","xlsx"])
    competitors_text = st.text_area("Or Enter Competitor Names (comma-separated)", placeholder="e.g., HUL, P&G, Dabur")
    rubric = st.selectbox("Choose rubric", ["None (show only uploaded columns)", "MOVI (Market/Offering/Value/Innovation)", "SWOT (Strength/Weakness/Opportunity/Threat)", "Custom (enter columns)"])
    custom_cols = []
    if rubric.startswith("Custom"):
        custom_in = st.text_input("Enter custom column names (comma-separated)", placeholder="e.g., Distribution, Price Corridor, Claims")
        custom_cols = [c.strip() for c in custom_in.split(",") if c.strip()]
    if st.button("Run Competitor Analysis", use_container_width=True):
        if uploaded_file:
            try:
                if uploaded_file.name.lower().endswith(".csv"):
                    df_comp = pd.read_csv(uploaded_file)
                else:
                    df_comp = pd.read_excel(uploaded_file)
            except Exception as e:
                st.error(f"Failed to read uploaded file: {e}")
                df_comp = pd.DataFrame()
        elif competitors_text.strip():
            comp_list = [c.strip() for c in competitors_text.split(",") if c.strip()]
            df_comp = pd.DataFrame({"Competitor": comp_list})
        else:
            df_comp = pd.DataFrame()
        if df_comp.empty:
            st.warning("No competitor data found.")
        else:
            st.success("✅ Competitor Data Loaded")
            if "Competitor" not in df_comp.columns:
                df_comp = df_comp.rename(columns={df_comp.columns[0]: "Competitor"})[["Competitor"]]
            if rubric == "None (show only uploaded columns)":
                st.subheader("📋 Uploaded Competitor Table")
                st.dataframe(df_comp, use_container_width=True)
            else:
                if rubric == "MOVI (Market/Offering/Value/Innovation)":
                    demo_values = {
                        "Market Share": ["High", "Medium", "Low"],
                        "Offering": ["Premium", "Mass", "Niche"],
                        "Value Proposition": ["Quality", "Price", "Reach"],
                        "Innovation": ["Strong", "Moderate", "Weak"]
                    }
                elif rubric == "SWOT (Strength/Weakness/Opportunity/Threat)":
                    demo_values = {
                        "Strength": ["Brand", "Distribution", "R&D"],
                        "Weakness": ["Price", "Portfolio gap", "Quality perception"],
                        "Opportunity": ["Channel expansion", "New segment", "Premiumization"],
                        "Threat": ["Regulation", "New entrants", "Raw material cost"]
                    }
                else:
                    demo_values = {c: [f"{c} A", f"{c} B", f"{c} C"] for c in custom_cols}
                for col, values in demo_values.items():
                    df_comp[col] = list(itertools.islice(itertools.cycle(values), len(df_comp)))
                st.subheader(f"📊 Competitor Table — {rubric.split()[0]}")
                st.dataframe(df_comp, use_container_width=True)
            st.download_button("⬇️ Download Competitor CSV", df_comp.to_csv(index=False).encode("utf-8"), file_name="competitor_analysis.csv")
