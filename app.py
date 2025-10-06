import streamlit as st
import pandas as pd
from googleapiclient.discovery import build
import tldextract
import re
import os
from dotenv import load_dotenv

# ----------------------
# CONFIGURATION
# ----------------------
load_dotenv()  # load .env variables
st.set_page_config(page_title="COMPEER'S AI", layout="centered")
st.title("COMPEER'S AI")

load_dotenv()

def get_key(name):
    # Try environment variable first
    key = os.getenv(name)
    if key:
        return key

    # Try Streamlit secrets if available (only on deployed app)
    try:
        if st.secrets and name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass

    return None


API_KEY = get_key("GOOGLE_API_KEY")
CSE_ID = get_key("GOOGLE_CSE_ID")

# ----------------------
# USER INPUTS
# ----------------------
cat = st.text_input("Category / Topic")
hint = st.text_input("Hints (comma-separated, optional)")
num_results = st.slider("Number of search results", min_value=5, max_value=10, value=10)

st.markdown("---")
st.write("Note: Add GOOGLE_API_KEY and GOOGLE_CSE_ID in environment variables or .env file for search to work.")

# ----------------------
# HELPER FUNCTIONS
# ----------------------
def google_search_raw(q, api_key, cse_id, num=10):
    service = build("customsearch", "v1", developerKey=api_key)
    resp = service.cse().list(q=q, cx=cse_id, num=num).execute()
    return resp.get("items", [])

PAYWALLED = {"nytimes.com", "wsj.com", "ft.com", "economist.com"}

def infer_publisher_and_type(url, title, snippet):
    ext = tldextract.extract(url)
    domain = ".".join(part for part in (ext.domain, ext.suffix) if part)
    publisher = domain if domain else url
    low = (domain or "").lower()
    src_type = "Other"

    if any(x in low for x in ("amazon", "flipkart", "walmart", "alibaba", "etsy")):
        src_type = "E-commerce"
    elif any(x in low for x in ("wikipedia", "edu")):
        src_type = "Academic"
    elif any(x in low for x in ("medium", "blogspot", "wordpress", "substack", "blog")):
        src_type = "Blog"
    elif any(x in low for x in ("news", "nytimes", "guardian", "reuters", "bbc", "thehindu", "economictimes")):
        src_type = "News"
    elif any(x in low for x in ("gov", "who.int", "un.org")):
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

# ----------------------
# RUN SEARCH
# ----------------------
if st.button("Run auto-discovery"):
    if not API_KEY or not CSE_ID:
        st.error("API_KEY or CSE_ID not set. Please check your .env file.")
    elif not cat.strip():
        st.warning("Enter a category/topic.")
    else:
        query = cat.strip()
        if hint.strip():
            query += " " + " ".join([h.strip() for h in hint.split(",") if h.strip()])

        try:
            items = google_search_raw(query, API_KEY, CSE_ID, num=num_results)
            st.session_state['items'] = items  # Save results
        except Exception as e:
            st.error(f"Search failed: {e}")
            st.session_state['items'] = []

# ----------------------
# DISPLAY RESULTS
# ----------------------
if 'items' in st.session_state and st.session_state['items']:
    items = st.session_state['items']
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

    approved = []
    st.markdown("### Select sources you want to approve")
    for i, r in short_df.iterrows():
        key = f"sel_{i}"
        checked = st.checkbox(f"[{r['source_type']}] {r['title']} — {r['publisher']}", key=key)
        if checked:
            approved.append(r)

    if st.button("Finalize shortlist"):
        if not approved:
            st.warning("Select at least one item.")
        else:
            final_df = pd.DataFrame(approved)
            st.session_state['final_df'] = final_df

            candidate_phrases = []
            for txt in (final_df['title'].astype(str) + " " + final_df['relevance_note'].astype(str)):
                tokens = re.findall(r"\b[A-Za-z]{4,}\b", txt)
                candidate_phrases.extend([t.lower() for t in tokens])
            freq = pd.Series(candidate_phrases).value_counts()
            suggestions = list(freq.head(8).index) if not freq.empty else []
            suggested_normalized = f"{suggestions[0].title()}" if suggestions else cat.strip().title()
            if len(suggestions) > 1:
                suggested_normalized += f" > {suggestions[1].title()}"

            st.success("Final shortlist ready ✅")
            st.subheader("Final Shortlist")
            st.dataframe(final_df.reset_index(drop=True))

            st.markdown("#### Suggested normalized category")
            st.info(suggested_normalized)

            csv_bytes = final_df.to_csv(index=False).encode('utf-8')
            st.download_button("Download Shortlist CSV", csv_bytes, file_name="whi_shortlist.csv")
