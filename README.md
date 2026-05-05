# Daily Milk Quality Agent

Local analysis package plus Outlook connector workflow for the Cobblestone milk quality report.

The Outlook Email connector handles mailbox access, attachment fetching, summary sending, and producer draft creation. The Python code in this repo handles deterministic CSV analysis, issue detection, duplicate suppression, and generation of connector-ready plain-text email payloads.

It can:

- Analyze the `4CS Current Month.csv` report.
- Flag `BF`, `SCC`, `SPC`, `PIC` (the report's PI column), and `LPC`.
- Write summary and producer draft previews.
- Write `connector_actions.json` shaped for the Outlook connector's `send_email` and `draft_email` tools.
- Finalize local history after connector-created producer drafts are made.

## Setup

1. Edit `config/settings.json`.
2. Set `outlook.summary_recipient` to your email address.
3. Fill in `producer_contacts` emails. Producers with blank emails are reported in the summary but skipped for Outlook Draft creation.
4. Confirm the Outlook Email connector is installed and authorized in Codex.

No Microsoft Entra app registration or client ID is required.

This repo has no required third-party Python packages. On this machine, the bundled Codex Python is:

```powershell
& 'C:\Users\DavidCummings\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' --version
```

## Local Analysis

Run a CSV analysis and generate connector-ready payloads:

```powershell
& 'C:\Users\DavidCummings\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\run_agent.py analyze-file 'C:\Users\DavidCummings\OneDrive - Cobblestone Milk Cooperative\Cobblestone\CS Reporting\Quality Reports\2026\04Sett1.csv'
```

The command writes:

- `summary.html` and `summary.txt`
- `producer_drafts/*.html` and `producer_drafts/*.txt`
- `connector_actions.json`
- `metadata.json`

The connector actions file contains:

- `summary_email`: payload for the Outlook connector `send_email` action.
- `producer_drafts`: one payload per producer for the Outlook connector `draft_email` action.
- `issue_keys`: local duplicate-suppression keys to finalize after drafts are created.

## Connector Automation

Print the daily Codex automation prompt:

```powershell
& 'C:\Users\DavidCummings\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\run_agent.py automation-prompt
```

The automation should run daily at `8:00 AM America/New_York`. It should use the Outlook Email connector to:

1. List recent Inbox messages ordered by `receivedDateTime desc`.
2. Find the first message from `noreply@dfamilk.com` with subject starting `4CS Current Month was executed at` and attachment `4CS Current Month.csv`.
3. Retry every 10 minutes until `9:00 AM` if the report is missing.
4. Fetch the CSV attachment and save it under `data/downloads/`.
5. Run `python run_agent.py analyze-file <downloaded_csv_path>`.
6. Read `connector_actions.json`.
7. Use connector `send_email` for `summary_email`.
8. Use connector `draft_email` for each item in `producer_drafts`.
9. Run `python run_agent.py finalize-connector-actions <connector_actions.json>` after drafts are created.

If the report is missing by `9:00 AM`, generate the missing-report connector payload:

```powershell
& 'C:\Users\DavidCummings\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' .\run_agent.py missing-report-actions
```

Then use the Outlook connector `send_email` action with `missing_report_email.payload`.

## Runtime Files

The agent writes local-only state under `data/`:

- `data/history.json`: duplicate suppression and run history.
- `data/downloads/`: connector-downloaded report CSV attachments.
- `data/reports/`: dry-run reports, draft previews, and connector action files.

These files are ignored by Git.

## Tests

```powershell
$env:PYTHONPATH = "$PWD\src"
& 'C:\Users\DavidCummings\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' -m unittest discover -s tests
```
