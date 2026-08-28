import os
import re
import sqlite3
from pathlib import Path
from datetime import datetime, timezone
from urllib.parse import quote_plus, urlparse

import requests
import streamlit as st

DB = Path("privacy_cleanup.db")

st.set_page_config(
    page_title="Privacy Cleanup",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

CSS = """
<style>
.block-container {max-width: 1220px; padding-top: 1.2rem; padding-bottom: 3rem;}
[data-testid="stSidebar"] {border-right: 1px solid rgba(128,128,128,.18);}
.hero {padding:1.3rem 1.4rem;border:1px solid rgba(128,128,128,.22);border-radius:18px;margin-bottom:1rem;}
.hero h1 {margin:0 0 .35rem 0;font-size:2rem;}
.muted {opacity:.72;}
.card {border:1px solid rgba(128,128,128,.22);border-radius:16px;padding:1rem;}
.badge {display:inline-block;padding:.18rem .52rem;border-radius:999px;border:1px solid rgba(128,128,128,.28);font-size:.78rem;margin-right:.25rem;}
.small {font-size:.87rem;opacity:.78;}
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

STATUSES = ["Found", "Review", "Request Ready", "Submitted", "Needs Verification", "Removed", "Rejected"]
RISK_OPTIONS = ["Low", "Medium", "High", "Critical"]

BROKERS = {
    "Spokeo": {"domain": "spokeo.com", "optout": "https://www.spokeo.com/optout"},
    "Whitepages": {"domain": "whitepages.com", "optout": "https://www.whitepages.com/suppression-requests"},
    "BeenVerified": {"domain": "beenverified.com", "optout": "https://www.beenverified.com/app/optout/search"},
    "TruePeopleSearch": {"domain": "truepeoplesearch.com", "optout": "https://www.truepeoplesearch.com/removal"},
    "FastPeopleSearch": {"domain": "fastpeoplesearch.com", "optout": "https://www.fastpeoplesearch.com/removal"},
    "PeopleFinders": {"domain": "peoplefinders.com", "optout": "https://www.peoplefinders.com/opt-out"},
    "Radaris": {"domain": "radaris.com", "optout": "https://radaris.com/control/privacy"},
}

def now():
    return datetime.now(timezone.utc).isoformat()


def safe_link_button(label, url, **kwargs):
    link_button = getattr(st, "link_button", None)
    if callable(link_button):
        return link_button(label, url, **kwargs)
    return st.markdown(
        f'<a href="{url}" target="_blank" rel="noopener noreferrer">{label}</a>',
        unsafe_allow_html=True,
    )


def rerun_app():
    rerun = getattr(st, "rerun", None)
    if callable(rerun):
        rerun()
        return
    experimental_rerun = getattr(st, "experimental_rerun", None)
    if callable(experimental_rerun):
        experimental_rerun()


def con():
    c = sqlite3.connect(DB)
    c.execute("""
      CREATE TABLE IF NOT EXISTS profile(
        id INTEGER PRIMARY KEY CHECK(id=1),
        full_name TEXT, email TEXT, username TEXT, phone TEXT
      )
    """)
    c.execute("""
      CREATE TABLE IF NOT EXISTS exposures(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source TEXT NOT NULL,
        url TEXT NOT NULL,
        identifier TEXT,
        data_type TEXT,
        risk TEXT NOT NULL DEFAULT 'Medium',
        status TEXT NOT NULL DEFAULT 'Found',
        confidence INTEGER NOT NULL DEFAULT 50,
        notes TEXT,
        discovered_by TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(url)
      )
    """)
    c.commit()
    return c

def load_profile():
    c = con()
    row = c.execute("SELECT full_name,email,username,phone FROM profile WHERE id=1").fetchone()
    c.close()
    return row or ("", "", "", "")

def save_profile(full_name, email, username, phone):
    c = con()
    c.execute("""
      INSERT INTO profile(id,full_name,email,username,phone)
      VALUES(1,?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET
        full_name=excluded.full_name,
        email=excluded.email,
        username=excluded.username,
        phone=excluded.phone
    """, (full_name, email, username, phone))
    c.commit()
    c.close()

def all_exposures():
    c = con()
    rows = c.execute("""
      SELECT id,source,url,identifier,data_type,risk,status,confidence,notes,discovered_by,created_at,updated_at
      FROM exposures ORDER BY updated_at DESC
    """).fetchall()
    c.close()
    return rows

def add_exposure(source, url, identifier="", data_type="Other", risk="Medium", confidence=50, notes="", discovered_by="Manual"):
    c = con()
    try:
        c.execute("""
          INSERT INTO exposures(source,url,identifier,data_type,risk,status,confidence,notes,discovered_by,created_at,updated_at)
          VALUES(?,?,?,?,?,'Review',?,?,?,?,?)
        """, (source, url, identifier, data_type, risk, confidence, notes, discovered_by, now(), now()))
        c.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        c.close()

def update_status(row_id, status):
    c = con()
    c.execute("UPDATE exposures SET status=?, updated_at=? WHERE id=?", (status, now(), row_id))
    c.commit()
    c.close()

def delete_local(row_id):
    c = con()
    c.execute("DELETE FROM exposures WHERE id=?", (row_id,))
    c.commit()
    c.close()

def valid_url(url):
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False

def identify_source(url):
    host = (urlparse(url).hostname or "").lower()
    for name, meta in BROKERS.items():
        if meta["domain"] in host:
            return name
    return host.replace("www.", "") or "Unknown"

def data_type_for(identifier, profile):
    name, email, username, phone = profile
    if identifier == email and identifier:
        return "Email"
    if identifier == phone and identifier:
        return "Phone"
    if identifier == username and identifier:
        return "Username"
    if identifier == name and identifier:
        return "Name"
    return "Other"

def request_text(name, identifier, url, source):
    return f"""Hello {source} Privacy Team,

I am requesting deletion or suppression of personal information about me that is publicly displayed by your service.

Name: {name or "[Your name]"}
Identifier: {identifier or "[Identifier]"}
Record URL: {url}

Please remove this record from public display and delete associated personal data where applicable and legally permitted.

Please confirm when this request has been completed.

Thank you."""

def serper_search(query, api_key, num=10):
    endpoint = "https://google.serper.dev/search"
    headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
    r = requests.post(endpoint, headers=headers, json={"q": query, "num": num}, timeout=20)
    r.raise_for_status()
    payload = r.json()
    return payload.get("organic", [])

def query_pack(profile):
    name, email, username, phone = profile
    identifiers = [x.strip() for x in [name, email, username, phone] if x and x.strip()]
    queries = []
    for ident in identifiers:
        queries.append((ident, f'"{ident}"'))
        for broker, meta in BROKERS.items():
            queries.append((ident, f'site:{meta["domain"]} "{ident}"'))
    return queries[:40]

def score_result(identifier, title, snippet, url):
    hay = f"{title} {snippet} {url}".lower()
    ident = identifier.lower()
    score = 35
    if ident and ident in hay:
        score += 40
    if any(b["domain"] in hay for b in BROKERS.values()):
        score += 15
    if any(word in hay for word in ["people", "profile", "address", "phone", "email", "record"]):
        score += 10
    return max(1, min(100, score))

def recheck_url(url, identifiers):
    try:
        r = requests.get(url, timeout=15, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0 PrivacyCleanup/1.0"})
        text = (r.text or "").lower()
        matches = [i for i in identifiers if i and i.lower() in text]
        return {
            "ok": True,
            "status_code": r.status_code,
            "still_present": bool(matches),
            "matches": matches[:4],
            "final_url": r.url,
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}

profile = load_profile()
rows = all_exposures()
total = len(rows)
removed = sum(1 for r in rows if r[6] == "Removed")
submitted = sum(1 for r in rows if r[6] == "Submitted")
review = sum(1 for r in rows if r[6] in ("Found", "Review", "Request Ready"))
pct = 100 if total == 0 else round(removed / total * 100)

with st.sidebar:
    st.subheader("🛡️ Privacy Cleanup")
    page = st.radio(
        "Navigation",
        ["Home", "1. My Info", "2. Auto Scan", "3. Review Findings", "4. Removal Center", "5. Verify", "Settings"],
        label_visibility="collapsed"
    )
    st.divider()
    st.caption("Local-first cleanup tracker.")
    st.caption("Automatic search can use your own Serper API key, stored only in this session.")

if page == "Home":
    st.markdown("""
    <div class="hero">
      <h1>Find it. Remove it. Verify it.</h1>
      <div class="muted">A guided privacy-cleanup workflow for public personal information.</div>
    </div>
    """, unsafe_allow_html=True)

    a,b,c,d = st.columns(4)
    a.metric("Tracked", total)
    b.metric("Needs review", review)
    c.metric("Submitted", submitted)
    d.metric("Verified removed", removed)
    st.progress(pct / 100 if pct else 0)
    st.caption(f"Cleanup progress: {pct}%")

    st.subheader("Workflow")
    c1,c2,c3,c4 = st.columns(4)
    c1.markdown('<div class="card"><b>1 · Save identifiers</b><br><span class="small">Name, email, username, phone.</span></div>', unsafe_allow_html=True)
    c2.markdown('<div class="card"><b>2 · Scan</b><br><span class="small">Search public results and broker domains.</span></div>', unsafe_allow_html=True)
    c3.markdown('<div class="card"><b>3 · Remove</b><br><span class="small">Open opt-outs and generate requests.</span></div>', unsafe_allow_html=True)
    c4.markdown('<div class="card"><b>4 · Verify</b><br><span class="small">Re-check listings until they are gone.</span></div>', unsafe_allow_html=True)

    st.info("No tool can guarantee deletion from every private database, backup, archive, ISP system, or third-party copy. This app focuses on public and legitimately removable data.")

elif page == "1. My Info":
    st.header("1. My Info")
    st.write("These identifiers are stored only in the local SQLite database in this app folder.")
    with st.form("profile_form"):
        full_name = st.text_input("Full name", value=profile[0])
        email = st.text_input("Email", value=profile[1])
        username = st.text_input("Username", value=profile[2])
        phone = st.text_input("Phone", value=profile[3])
        if st.form_submit_button("Save locally", type="primary"):
            save_profile(full_name.strip(), email.strip(), username.strip(), phone.strip())
            st.success("Saved.")
            rerun_app()

elif page == "2. Auto Scan":
    st.header("2. Auto Scan")
    st.write("The scanner can use a search API you control. This avoids scraping search-engine result pages directly.")

    identifiers = [x for x in profile if x]
    if not identifiers:
        st.warning("Add at least one identifier in **My Info** first.")
    else:
        st.subheader("Manual one-click scan")
        st.caption("These buttons open searches in your browser without sending anything to this app's server.")
        for ident in identifiers:
            q = quote_plus(f'"{ident}"')
            cols = st.columns(3)
            safe_link_button(f'Google: {ident[:22]}', f"https://www.google.com/search?q={q}")
            safe_link_button("Bing", f"https://www.bing.com/search?q={q}")
            safe_link_button("DuckDuckGo", f"https://duckduckgo.com/?q={q}")

        st.divider()
        st.subheader("Automatic discovery")
        api_key = st.text_input("Serper API key", type="password", help="Optional. Used only for this scan session and not written to the database.")
        max_queries = st.slider("Search depth", 4, 24, 8, 2)

        if st.button("Run automatic scan", type="primary", disabled=not bool(api_key)):
            queries = query_pack(profile)[:max_queries]
            found = 0
            with st.status("Scanning public search results...", expanded=True) as status:
                for idx, (identifier, query) in enumerate(queries, start=1):
                    st.write(f"{idx}/{len(queries)} — {query}")
                    try:
                        for item in serper_search(query, api_key, num=10):
                            url = item.get("link", "")
                            if not valid_url(url):
                                continue
                            title = item.get("title", "")
                            snippet = item.get("snippet", "")
                            confidence = score_result(identifier, title, snippet, url)
                            source = identify_source(url)
                            dtype = data_type_for(identifier, profile)
                            risk = "High" if confidence >= 80 else "Medium"
                            if add_exposure(
                                source, url, identifier, dtype, risk, confidence,
                                notes=(title + " — " + snippet)[:700],
                                discovered_by="Automatic scan"
                            ):
                                found += 1
                    except Exception as e:
                        st.warning(f"Search failed for one query: {e}")
                status.update(label=f"Scan complete — {found} new results queued", state="complete")
            st.success(f"Added {found} new possible exposures for review.")

elif page == "3. Review Findings":
    st.header("3. Review Findings")
    st.write("Review automatic matches before treating them as real exposures.")

    candidates = [r for r in rows if r[6] in ("Found", "Review")]
    if not candidates:
        st.info("No findings need review.")
    else:
        for r in candidates:
            row_id, source, url, identifier, data_type, risk, status, confidence, notes, discovered_by, created_at, updated_at = r
            with st.container(border=True):
                st.markdown(f"**{source}**")
                st.markdown(f'<span class="badge">{confidence}% match</span><span class="badge">{risk} risk</span>', unsafe_allow_html=True)
                st.write(url)
                if identifier:
                    st.caption(f"Matched identifier: {identifier}")
                if notes:
                    st.write(notes)
                c1,c2,c3 = st.columns(3)
                safe_link_button("Open result", url)
                if c2.button("This is me", key=f"yes_{row_id}", type="primary"):
                    update_status(row_id, "Request Ready")
                    rerun_app()
                if c3.button("Not me / remove finding", key=f"no_{row_id}"):
                    delete_local(row_id)
                    rerun_app()

elif page == "4. Removal Center":
    st.header("4. Removal Center")
    ready = [r for r in rows if r[6] in ("Request Ready", "Submitted", "Rejected")]
    if not ready:
        st.info("Approve findings in **Review Findings** first.")
    else:
        for r in ready:
            row_id, source, url, identifier, data_type, risk, status, confidence, notes, discovered_by, created_at, updated_at = r
            with st.expander(f"{source} · {data_type} · {status}", expanded=status=="Request Ready"):
                st.write(f"**Public record:** {url}")
                c1,c2 = st.columns(2)
                safe_link_button("Open record", url)
                if source in BROKERS:
                    safe_link_button("Open official opt-out page", BROKERS[source]["optout"])
                st.text_area(
                    "Removal request",
                    request_text(profile[0], identifier, url, source),
                    height=220,
                    key=f"req_{row_id}"
                )
                new_status = st.selectbox(
                    "Status",
                    STATUSES,
                    index=STATUSES.index(status),
                    key=f"status_{row_id}"
                )
                if new_status != status:
                    update_status(row_id, new_status)
                    rerun_app()

elif page == "5. Verify":
    st.header("5. Verify")
    st.write("The verifier performs a normal HTTP request to the saved public URL and checks whether your saved identifiers still appear in the returned page text.")
    ids = [x for x in profile if x]
    candidates = [r for r in rows if r[6] in ("Submitted", "Needs Verification", "Removed")]

    if not candidates:
        st.info("Nothing is ready to verify.")
    else:
        for r in candidates:
            row_id, source, url, identifier, data_type, risk, status, confidence, notes, discovered_by, created_at, updated_at = r
            with st.container(border=True):
                st.write(f"**{source}** — {status}")
                st.write(url)
                c1,c2,c3 = st.columns(3)
                safe_link_button("Open page", url)
                if c2.button("Auto re-check", key=f"check_{row_id}"):
                    result = recheck_url(url, ids)
                    if not result.get("ok"):
                        st.warning(f"Could not verify automatically: {result.get('error')}")
                    else:
                        code = result["status_code"]
                        if code in (404, 410):
                            st.success(f"Page returned {code}. This is strong evidence the record is gone.")
                        elif result["still_present"]:
                            st.error("One or more saved identifiers still appear in the returned page.")
                            st.write(result["matches"])
                            update_status(row_id, "Needs Verification")
                        else:
                            st.success("Saved identifiers were not found in the returned page text. Manually open the page to confirm before marking removed.")
                if c3.button("Mark verified removed", key=f"rm_{row_id}", type="primary"):
                    update_status(row_id, "Removed")
                    rerun_app()

elif page == "Settings":
    st.header("Settings")
    st.write("Local database: `privacy_cleanup.db`")
    st.warning("Deleting this database only removes your local tracker. It does not delete anything from the internet.")
    st.subheader("Known opt-out directory")
    for name, meta in BROKERS.items():
        safe_link_button(f"{name} opt-out", meta["optout"])

    with st.expander("Delete local findings"):
        for r in rows:
            if st.button(f"Delete #{r[0]} — {r[1]}", key=f"delete_{r[0]}"):
                delete_local(r[0])
                rerun_app()
