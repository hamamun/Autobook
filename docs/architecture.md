# Autobook — Architecture Proposal

**Status:** design draft, awaiting approval. No code written.

**Confirmed constraints**

| Constraint | Value |
|---|---|
| Deployment | Windows install, single user, one PC |
| Target site | Works fully in current Microsoft Edge (modern, no IE mode) |
| Transport | Both field-by-field entry **and** Excel/CSV upload are available |
| Supervision | Visible browser window, fully automatic submit — user watches and can intervene |
| Input documents | PDF and Excel |
| Output | A new Excel database, then submission to the website |

Because the site works in modern Edge and supports file import, **Python is confirmed as the
correct language choice** and the highest-risk objection (legacy ActiveX) is eliminated.

---

## 1. Stack

| Concern | Choice | Notes |
|---|---|---|
| Language | Python 3.12 | 64-bit |
| Browser control | Playwright (Python), `channel="msedge"`, headed mode | Drives installed Edge. No bundled Chromium → small installer |
| PDF text | pdfplumber; PyMuPDF for speed/edge cases | Choose per-document by trying the text layer first |
| PDF tables | camelot (lattice/stream) as a fallback | Only needed for spec-sheet style PDFs |
| OCR | PaddleOCR or Tesseract — **optional module** | Only if scanned PDFs actually appear in real input |
| Excel read/write | pandas + openpyxl (xlsxwriter if heavy styling) | openpyxl for round-tripping the site's own template |
| Local database | SQLite (bundled with Python) | Source of truth. Excel is an export, not the store |
| Secrets | `keyring` → Windows Credential Manager (DPAPI) | Per-user, no plaintext password on disk. Never in the workbook |
| Config | YAML, validated by pydantic | Field mappings live in config, not code |
| Logging | `logging` + rotating file in `%LOCALAPPDATA%` | Screenshot/HTML captured on failure |
| UI | Phase 1: CLI (`typer`). Phase 2: Streamlit local tab | Streamlit is the cheapest way to give operators buttons |
| Packaging | PyInstaller `--onedir` wrapped in Inno Setup | Per-user install, no admin rights, Start Menu shortcut |

Deliberately avoided: Excel as live storage (corruption/loss risk when the file is open),
`--onefile` packaging (slow startup with Playwright), and any CAPTCHA-solving.

---

## 2. Pipeline

```
  ┌──────────────┐   ┌───────────────┐   ┌──────────────┐   ┌─────────────────┐
  │ 1. INGEST    │   │ 2. EXTRACT    │   │ 3. REVIEW    │   │ 4. SUBMIT       │
  │ PDF + Excel  │──▶│ normalise to  │──▶│ human fixes  │──▶│ Playwright →    │
  │ in /inbox    │   │ record rows   │   │ low-conf rows│   │ site (headed)   │
  └──────────────┘   └───────────────┘   └──────────────┘   └────────┬────────┘
                            │                    │                   │
                            ▼                    ▼                   ▼
                     ┌──────────────────────────────────────────────────┐
                     │            SQLite: records + audit               │
                     └──────────────────────┬───────────────────────────┘
                                            ▼
                                  Excel export / report
```

Four stages, each independently testable and re-runnable. A record never leaves a stage
without a state change being committed, so a crash mid-run is always recoverable.

### Stage 1 — Ingest
- Watch or scan a folder (`inbox/`), or take a path from the CLI.
- Detect PDF vs xlsx/xls/csv by sniffing content, not just extension.
- Hash each file (SHA-256) and store it — **re-running the same file is a no-op**, never a
  duplicate booking. This is the idempotency guard.
- Keep the original file path so any extracted value can be traced back to its source page.

### Stage 2 — Extract
- **Excel input:** column-name mapping per supplier template → canonical fields.
- **PDF input:** per-template extraction profile (which page, which label, regex or table
  column). A template that doesn't match is routed to review, never guessed silently.
- Scanned page → OCR path, or straight to review if OCR confidence is low.
- Output: one `record` per booking/entry with a **confidence score per field** and the
  source location (`file`, `page`, `cell`) for each value.
- Normalisation happens here once: dates → ISO, names/addresses trimmed and cased, phone
  numbers, currency amounts, and enum values matched to the site's dropdown options.

### Stage 3 — Review
- Only low-confidence or missing/ambiguous fields surface — not the whole dataset.
- Operator edits are logged with a timestamp and who changed what.
- Excel export of the current dataset, so the operator has a familiar view and can keep a
  copy. Edits in the exported file can be re-imported with a matching key (Phase 2; the
  approved path is: edit in the app, export for reading).

### Stage 4 — Submit
Two backends behind one interface, selected per record:

- **Form mode:** navigate, `fill()` each mapped field, select dropdowns/radios, handle
  date pickers, upload attachments with `set_input_files()`.
- **File mode:** generate the site's exact import workbook from SQLite, upload it, then
  `expect_download()` the receipt and **parse the receipt back** to confirm each row's
  server-side result. "Upload succeeded" is not evidence that a row was accepted.

Execution model for the confirmed "visible but automatic" choice:
1. Launch Edge visible, restore the saved authenticated session.
2. Process records one at a time; announce each in the log/UI ("3 of 12 — ref 88213").
3. A **visible stop control** (UI button, or `Ctrl+Alt+S` global stop) halts before the next
   submission. Abort mid-form leaves nothing submitted because the final Save click is the
   last action, guarded by a check that the record is still `queued`.
4. Optional guardrail: a per-run cap (e.g. max 20 submissions) and a pause between records,
   so a mapping error is caught after two bad entries instead of all of them.
5. Capture screenshot + page HTML on every failure and every successful confirmation.

**Session handling:** first run, the user signs in manually in the visible window
(CAPTCHA/2FA handled by the human, legitimately). `storage_state` is persisted so later
runs reuse the session until it expires; expiry is detected by the login page appearing and
triggers a re-auth prompt rather than a silent failure. Credentials from Credential Manager
are only used to pre-fill the username/password boxes.

---

## 3. Module layout

```
Autobook/
├─ pyproject.toml
├─ config/
│  ├─ settings.yaml          # paths, run caps, timeouts, log level
│  ├─ site.yaml               # selectors, field map, import template spec, URLs
│  ├─ templates/
│  │  ├─ supplier_a.yaml      # PDF extraction profile
│  │  └─ supplier_b.yaml
│  └─ field_map.yaml          # canonical field ↔ site label/dropdown mapping
├─ autobook/
│  ├─ cli.py                  # ingest / extract / review / submit / export
│  ├─ settings.py             # pydantic config models
│  ├─ ingest/                 # sniffing, hashing, dispatch
│  ├─ extract/                # pdf_*, excel, ocr, normalise, confidence
│  ├─ store/                  # schema, migrations, repository
│  ├─ export/                 # excel writer, template builder
│  ├─ submit/                 # browser driver, form mode, file mode, session, receipt parser
│  ├─ ui/                     # phase 2 Streamlit screens
│  └─ util/                   # logging, paths, keyring wrapper, retry
├─ tests/
│  ├─ fixtures/               # anonymised sample PDFs, workbooks, saved HTML pages
│  └─ ...
└─ packaging/
   ├─ autobook.spec           # PyInstaller, onedir
   └─ installer.iss           # Inno Setup, per-user
```

The important separation: **selectors and mappings live in YAML, not Python.** When the
site changes a label, that's a config edit; when the logic changes, that's code. This is
what keeps maintenance cheap over years.

---

## 4. Data model (SQLite)

```
source_file   id, path, sha256 UNIQUE, kind(pdf|xlsx|csv), received_at, status
template      id, name, kind, profile_yaml_path, version
record        id, batch_id, natural_key UNIQUE, status, submitted_via, site_reference,
              confidence_min, created_at, updated_at
record_field  record_id, field_name, value, raw_value, confidence, source_locator
record_file   record_id, field_name, stored_path, sha256          -- attachments to upload
review_log    record_id, field_name, old_value, new_value, actor, at
submission    id, record_id, mode, started_at, ended_at, outcome, http_status,
              screenshot_path, html_path, message, receipt_path
run           id, kind, started_at, ended_at, operator, records_total, records_ok,
              records_failed
```

**States:** `extracted → needs_review → ready → queued → submitting → confirmed`
(with `failed` and `skipped` as terminal side-branches). Only `queued` can be submitted,
and submission flips it to `submitting` in a transaction first — that is what prevents a
double booking under retry.

`natural_key` is the dedupe identity: a hash of the business-identifying fields (e.g.
booking reference + date + passenger/patient name). If the same key appears again from a
newer file, the record is updated and the prior submission retained in the audit trail.

---

## 5. Config shapes (illustrative, not final)

`site.yaml` — one file per portal, so a second site is a new file, not a fork:

```yaml
name: portal-a
base_url: ...
login:
  url: ...
  username_selector: ...
  password_selector: ...
  submit_selector: ...
  success_selector: ...
form:
  entry_url: ...
  fields:
    booking_ref:  { selector: ..., type: text }
    travel_date:  { selector: ..., type: date }
    service_type: { selector: ..., type: select, options: { standard: "STD", express: "EXP" } }
  save_selector: ...
  confirm_selector: ...
import:
  enabled: true
  template_path: templates/portal_a_import.xlsx
  upload_selector: ...
  download_receipt_selector: ...
```

`templates/supplier_a.yaml` — how to read one supplier's PDF/Excel:

```yaml
kind: pdf
match:  { first_page_contains: "Booking Confirmation" }
fields:
  booking_ref: { page: 1, regex: 'Booking Ref[: ]+([A-Z0-9-]+)', required: true }
  travel_date: { page: 1, label: "Travel Date", parser: date_dmy }
  amount:      { page: 1, table: { index: 0, column: "Total" }, parser: money }
```

---

## 6. Risks and mitigations

| Risk | Impact | Mitigation |
|---|---|---|
| Scanned PDFs appear later | Extraction silently produces junk | Text-layer check per page; OCR path with confidence threshold; anything below threshold goes to review |
| Site layout/labels change | Submission breaks | Role/label-based locators, config-driven mapping, saved-HTML fixture tests that fail loudly |
| Session expires mid-run | Partial batch, confusing state | Detect login page, pause and prompt re-auth, resume from the last unsubmitted record |
| Duplicate submission on retry | Real-world damage (double booking) | Unique `natural_key` + transactional state transition + re-check before final Save |
| Wrong record submitted | Money/customer impact | Visible browser (confirmed), review gate on low confidence, per-run cap, stop control |
| Antivirus flags unsigned installer | User can't install | Code-sign the installer; or acceptable for one internal PC with the "More info → Run anyway" step documented |
| Excel template drift from the portal | Import rejected | Receipt parsing catches per-row rejects; template version pinned in config and checked before upload |
| `%LOCALAPPDATA%` files lost on reinstall | Losing audit trail | Installer leaves data dir on uninstall; `backup` command writes a timestamped copy elsewhere |
| Terms-of-service limits on automation | Account risk | Confirm with the site owner; keep volume human-scale; human-controlled login |

---

## 7. Milestones

| # | Deliverable | Exit test |
|---|---|---|
| 0 | Spike: log in, fill one form, submit one test record, upload one file (throwaway script) | Proves the site is automatable in Edge with your real account — do this before any architecture is committed |
| 1 | Config + SQLite + ingest + Excel extraction + Excel export (no browser) | 100 real Excel files → a correct, deduped workbook |
| 2 | PDF extraction for the top 2–3 supplier templates + review UI (minimal) | Correct fields for known templates; unknown templates land in review, never in the output as garbage |
| 3 | Submit: form mode with session reuse, stop control, screenshots, receipt parsing | 20 test records submitted and confirmed with an audit trail |
| 4 | Packaging: PyInstaller onedir + Inno Setup, Credential Manager, logging, data backup | Fresh Windows install, no admin rights, runs end to end |
| 5 | File mode (bulk template upload), second site profile if needed, Streamlit UI | Bulk path produces the same confirmed records as form mode |

Milestone 0 is deliberately separate: roughly a day of work that de-risks everything else.
If the site proves awkward to automate (frames, shadow DOM, aggressive session timeouts),
that is discovered before the eight-week build, not after.

---

## 8. Open questions

1. Roughly how many supplier document formats (distinct layouts) exist today, and do any
   arrive as scans/photos?
2. What is the realistic record volume per day/week? (Decides whether Streamlit + SQLite is
   overkill or appropriate.)
3. Which field in the source documents is the business identity for dedupe — booking
   reference, order number, customer + date?
4. Is the portal vendor reachable to ask about an API or agreed import template?
5. Who is the operator, and is a command line acceptable for phase 1 or is a screen needed
   from day one?
