# Privacy Cleanup v3

A local-first privacy cleanup application with a guided:

**Scan → Review → Remove → Verify**

workflow.

## Features

- Local profile for the identifiers you want to clean up.
- One-click public web searches.
- Optional automatic discovery using your own Serper API key.
- Data-broker focused queries.
- Confidence scoring for possible matches.
- Human review before a result is treated as yours.
- Removal request generator.
- Official opt-out shortcuts for common people-search services.
- Status tracking.
- Automatic URL re-checking for submitted removals.
- Verified-removed workflow.

## Install

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

### Windows PowerShell

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
streamlit run app.py
```

## Automatic scanning

The app supports Serper for automated Google-result discovery.

1. Get your own Serper API key.
2. Paste it into the **Auto Scan** page.
3. Run the scan.
4. The key is used only for that Streamlit session and is not saved to SQLite.

The app deliberately does not scrape Google/Bing result HTML directly.

## What "verified removed" means

A record can be marked verified removed when you have confirmed the public listing is no longer exposing your information.

The automatic verifier helps by:
- checking the saved URL,
- reporting 404/410 results,
- searching returned page text for your saved identifiers.

Manual confirmation is still recommended because many sites render data with JavaScript or use anti-bot protections.

## Important limitation

No application can honestly guarantee complete deletion from the entire internet. Copies can remain in:

- private company databases,
- backups,
- archives,
- screenshots,
- lawful retention systems,
- ISP/network logs,
- decentralized copies,
- third-party databases you cannot control.

This application focuses on public and legitimately removable personal data.
