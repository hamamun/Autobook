# Maersk SCP — the operator's click path

Recorded from the operator's screenshots, step by step. This is the specification the
filling automation follows; it is written in the operator's order, not the code's.

Status: **collecting steps**. No code written against this file yet.

## Two ways to get a logged-in browser

The run needs a browser that is already logged in. There are two ways to provide one, and
only the first ever opens a window of its own.

### Signing in — Autobook never sees your password

No credentials are given to Autobook, stored in settings, or written to disk. The
password is typed into **Maersk's own sign-in page**, in the browser window. Autobook
only ever inherits the resulting session.

On **Start filling**:

1. The browser opens and loads the portal.
2. If the portal lands on a sign-in page, the log says
   *"Sign in to Maersk in the browser window. Autobook is waiting..."* and the run
   **waits up to 10 minutes** for you to finish, including any 2FA.
3. Sign in normally. The run notices the portal has loaded and carries on by itself.
4. If the session is still valid from a previous run, step 2 is skipped entirely - no
   window prompt, no waiting.

The session is kept in `browser-profile/`. It expires on Maersk's schedule, not ours, so
occasionally you will be asked to sign in again - which is exactly step 2.

**How "logged in" is judged** (from the real sign-in URL):

| URL | Verdict |
|---|---|
| `accounts.maersk.com/ocean-maeu/auth/login?...` | not signed in - **the real sign-in page** |
| `maersk.com/portaluser/oidc/callback?code=...` | not signed in - mid-redirect |
| `maersk.com/scp/...` | signed in |
| `about:blank` | not signed in - a fresh tab, not a loaded portal |

Note the plural in `accounts.maersk.com`: an earlier guess of `account.maersk.com` would
never have matched, and the run would have waited the full ten minutes on a page it
should have recognised instantly.

### A. Autobook's own browser (default)

Click **Start filling** and a browser window opens. That window is the automation's, not
yours - you log in **inside it**, once, and the session is stored in
`browser-profile/`, so later runs start logged in.

Why a separate window at all: current Edge and Chrome **refuse remote debugging on the
default profile**, so an automation-controlled browser must use its own profile folder.
There is no way to drive the Edge you are already browsing in.

### B. Attach to a browser you started (no new window)

Start Edge yourself with debugging enabled **and a non-default profile**:

```
& "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" ^
    --remote-debugging-port=9222 ^
    --user-data-dir="%LOCALAPPDATA%\Autobook\edge-debug" ^
    https://www.maersk.com/scp
```

Log in there. Then either set `"browser_mode": "attach"` in `settings.json` or run
`scripts/run_fill.py --attach`. Nothing new opens; the run uses the window you are
watching.

The `--user-data-dir` flag is not optional - Edge will ignore the debugging port on the
default profile.

| | A - own browser | B - attach |
|---|---|---|
| Opens a window | **yes**, once per run | no |
| Log in | once, inside it | once, inside your own |
| Uses your normal Edge window | no | no |
| Requires a command line | no | yes, every time |

---

## The flow so far

```
login → Export ▸ Bookings → Filters → Order = PO → Apply filters
                                    │
              ┌─────────────────────┴──────────────────────┐
              │                                            │
      "No bookings found"                        1+ rows: read Status
      record + report                                    │
                                        ┌────────────────┴───────────────┐
                                        │                                │
                              Cancel / Stuffed                  anything else
                              record + skip → next PO                    │
                                                             several rows?
                                                          ┌──────┴──────┐
                                                        yes            no
                                                    ask user       use the row
                                                          └──────┬──────┘
                                                                 │
                                                  click booking number
                                                                 │
                                                    Edit booking ─┘
                                                                 │
                                     ┌───────────────────────────┴──────────┐
                                     │  commercial invoice currency = USD   │
                                     │  expand PO card if collapsed         │
                                     │  match PO + SKU core                 │
                                     │  fill qty / volume / weight / pkgs   │
                                     │  description + commodity only if blank│
                                     │  cargo type = Flat pack              │
                                     │  unmatched SKU → skip + report       │
                                     └───────────────────────────┬──────────┘
                                                                 │
                                                              Review
                                                                 │
                                        compare J/L/N/O + row-wise SKU
                                                                 │
                                              all match and Errors: 0?
                                                    ┌────┴────┐
                                                   no        yes
                                             report  │       submit
                                                     │        │
                                                     └────┬───┘
                                                          │
                                    back to list → filter same PO → read Status
                                                          │
                              ┌───────────────────────────┴──────────────┐
                              │                                          │
                Pending for confirmation / Booking confirmed      anything else
                        success → next PO                    not done → report
```

## Step 1 — Export ▸ Bookings

Precondition: logged in to `maersk.com/scp`.

1. In the left navigation rail, click **Export**.
   - Hovering it opens a flyout with three entries: **Orders**, **Bookings**,
     **Order Planning**.
2. In the flyout, click **Bookings**.

Result: the **Bookings** list page.

### What the list page contains

| Element | Observed |
|---|---|
| Title | `Bookings` |
| Toolbar left | `Filters`, `Save filters`, and a date chip |
| Toolbar right | `Batch upload ▾`, `Create booking`, `Customize` |
| Columns | checkbox · Booking · Contractual custo… · Contractual custo… · Contractual custo… · Order · SKUs · Header invoice numbers · Status · Consignee · Consignee BE Cod… |
| Booking cell | a link, e.g. `SBK0005269616` (blue, clickable) |
| Order cell | the order number, truncated: `45000500…`, `45000467…` |
| SKUs cell | `Multiple (3)`, `Multiple (1…` — a count, not the SKU list |
| Status cell | green pill, e.g. `Booking confirmed` |

### Notes for the automation

- The left-nav **Export** item opens a **flyout**, not a plain link: click Export, then
  click Bookings. A single click on Export alone does not navigate.
- A date filter is present in the toolbar. It is **not part of the mapping** - the
  automation leaves it alone.
- The **Order** column is truncated on screen. Whatever we match against must be read
  from the cell's full value, not the visible ellipsis.
- One PO shows as `Multiple (3)` in SKUs, so a single booking can carry several SKUs.

---

## Step 2 — Open the Filters panel

On the Bookings list page (the state reached at the end of step 1), click **Filters** in
the toolbar above the table.

Result: the filter panel opens. The PO / order number field is inside it (step 3).

### What matters here

- **The toolbar shifts.** The date chip and `Save filters` come and go between visits, so
  **`Filters` is located by its own label, never by position.**
- **The Order column carries varying formats** (`45000500…`, `POEU6702…`, `POUKR670…`).
  This is why the filter is driven by the **field name** (`Order`), never by the shape of
  the value.
- Status values vary too; step 4 records which ones skip.

## Step 3 — Type the PO into `Order` and apply

With the Filters panel open (step 2):

1. In the panel, under **Reference**, find the field labelled **`Order`**.
   Not `Booking`, not `SKU`, not `Customer reference`. The **field name is what
   matters** - the PO's own format varies (`4500036312`, `POEU450245255333`, …) and the
   automation must never pattern-match it.
2. Type the PO number from the data sheet — the Booking_lines `PO no` value, taking the
   **first** one for the first run.
3. Click **`Apply filters`** at the bottom of the panel.

Result: the list narrows to the matching booking(s); step 4 covers what appears.

### The Filters panel, as observed

| Element | Detail |
|---|---|
| Header tabs | `Filters` \| `Saved filters`, with an ✕ to close the panel |
| Search | `Search all filters` box - finds a field by name |
| Section | **`Reference`** (scrollable; there is a second section below, off-screen) |
| Reference fields used | **`Order`** only. `Booking` and `SKU` exist and may be used later; every other field is not required - the panel offers `Equipment`, `Carrier booking confirmation number`, `CLP number`, `CLR`, `Customer reference`, `Consolidation ID`, `Header invoice numbers`, `S1`, `S2`, `S3` |
| Footer buttons | **`Apply filters`** (dark/primary) and `Clear filters` |
| Panel scroll | the field list has its own scrollbar - the footer buttons sit below it, outside the scroll area |

### Operational details for the automation

- **The applied PO appears as a chip** in the toolbar (e.g. `4500046108 ✕`) next to
  `Filters` and `Save filters` - a visual check that our filter took effect.
- **`Clear filters` is not a reset of everything.** It is next to `Apply filters` and is
  the safe way to undo our PO between runs - relevant because we process POs one after
  another (see open questions).
- **`Apply filters` is required.** Typing into `Order` changes nothing until it is
  clicked; the list only updates after.
- the `Order` field is a plain text box (no dropdown), so no option list to match.

---

## Step 4 — The filtered result, and reading its status

After `Apply filters` (step 3) the list narrows to the matching row(s):

| Element | Observed |
|---|---|
| Toolbar chip | `4500046108 ✕` — the applied PO, replacing the date chip |
| Pagination | `1-1 of 1` — a count of matched rows |
| Booking cell | `SBK0005171699` in **red**, with an ⓘ info icon beside it |
| Order cell | `45000461…` (truncated) |
| SKUs | `Multiple (1…` |
| Status | **`Pending for confirmation`** — amber pill |
| Hovered link | `.../ordermanagement/bookings/details/0005171699/USGYMSHAR5HQ` |

Then **click the booking number** to open the booking.

### Reading the status — the decision on this page

The Status column decides whether the PO is worked at all:

| Status | Action |
|---|---|
| **`Cancel`** | **Skip.** Record on the report. Do not open, do not fill. |
| **`Stuffed`** | **Skip.** Record on the report. Do not open, do not fill. |
| Anything else | Proceed. |

Seen so far: `Booking confirmed` and `Pending for confirmation` proceed; `Stuffed` and
`Cancel` are skipped. The report that records a skipped PO is later work — this step only
detects and skips.

**Matching must be exact, not substring.** `Stuffed` is a skip, so a name like
`Unstuffed` or `Partially stuffed` must not be swept up by a naive "contains stuffed"
test. Compare the whole status label, case-insensitively, after trimming whitespace.

**Anything unrecognised proceeds.** The skip list is explicit and short; a status we have
never seen goes ahead rather than being silently blocked, and shows on the report so the
list can be extended.

### Details worth noting

- **The booking number's colour is cosmetic** and varies for several reasons (red here,
  blue in earlier screenshots). It carries no meaning: **the status is the only thing
  that decides.**
- **`1-1 of 1` is a cheap sanity check** that the filter matched exactly one row,
  available before anything is clicked.
- **The URL contains the booking id**: `bookings/details/<id>/<customer-code>`. If
  clicking proves fragile, navigating to that URL is a fallback.
- Only the matched rows remain in the table, so re-filtering means `Clear filters` first
  (decided in step 3).

### Not covered by the screenshots

- **A PO matching no rows.** The list comes back empty. Per the operator, this is **how
  the portal is designed**: after filtering by PO, the matching booking(s) appear but
  **the PO number itself is not shown anywhere in the row**, so its absence proves
  nothing. The filter result is trusted as-is.

  Therefore: an empty result means **"PO not found"** - recorded and reported, never
  treated as completed.
- **Multiple rows for one PO.** Covered by the decision already taken: pause and ask
  which booking, before any status is read.

---

---

## Step 4a — If the status is `Cancel` or `Stuffed`: record and skip

Read the Status column of the filtered row(s) **before** clicking anything.

| Status | Action |
|---|---|
| `Cancel` | **Record it on the report. Skip the booking.** Do not open, do not fill. |
| `Stuffed` | **Record it on the report. Skip the booking.** Do not open, do not fill. |
| anything else | continue to step 4b |

- The report itself is later work; this step only detects the two statuses, records the
  booking number and status, and moves on to the next PO.
- **Exact label match**, trimmed and case-insensitive. `Stuffed` must not catch
  `Unstuffed` / `Partially stuffed`.
- An unrecognised status proceeds.

## Step 4b — If more than one booking matches: ask the user

When the PO filter returns **two or more** booking rows, the automation **pauses** and
asks which booking to work on. It does not guess, and it does not work them all.

| Element | Detail |
|---|---|
| Trigger | the filter result shows more than one row |
| Shown to the user | the booking number of each candidate, plus SKU count and status (both already in the row) |
| User action | pick one |
| Then | read the status of the chosen row (step 4a) and continue if it is not a skip |

`Cancel` / `Stuffed` rows are reported as skipped by step 4a and are **not** offered as
choices. If **every** matching booking is a skip status, nothing is offered and the PO is
recorded as skipped.

---

## Step 5 — "No bookings found" (the skip case)

When the PO matches nothing, the page states it plainly:

| Element | Observed |
|---|---|
| Toolbar chips | the PO chip appears alongside the date chip, e.g. `4500060896 ✕` |
| Pagination | `0-0 of 0` |
| Table body | empty |
| Message | **`No bookings found`** with `Try adjusting your filters or search criteria.` |

Record it and report it. The report is later work; this step only detects.

**This is a positive signal, not an inference.** Because the portal names the condition
in its own text, the automation can wait for `No bookings found` instead of inferring
"empty table" from zero rows - which is far less ambiguous than counting `<tr>` elements.
The `0-0 of 0` counter corroborates it.

The date chip is not part of the mapping. It is left exactly as found; the automation
never reads, sets or clears it.

---

## Step 6 — The booking page, and `Edit booking`

Clicking the booking number opens the booking's own page.

### Header

| Element | Observed |
|---|---|
| Back link | `← Bookings` (top left) |
| Heading | the booking number, e.g. `SBK0005163614` |
| Actions (top right) | **`Edit booking`** · `Cancel booking` · `Download PDF` |

### Summary blocks above the tabs

| Block | Contents |
|---|---|
| Status strip | `Booking status` (green pill, e.g. `Booking confirmed`) · `Customer reference` · `Creation date` · `Last updated` |
| **Shipment summary** | `Place of receipt site`, `Place of empty pickup site`, `Port of loading site`, `Port of discharge site`, `Place of delivery site` - each with a code beneath |
| **Shipment** card | `Receipt date`, `Cargo ready date`, `Expected Delivery Date` |
| **Container** card | `Empty pick up`, `Requested ETD`, `Requested ETA` |
| Tabs | **`Booking details`** (active) · `Parties` · `History` |

### `Booking details` section (read-only, below the tabs)

Two/three-column list: `Shipper`, `Origin service`, `Origin Service Sub Type`,
`Shipment mode - origin`, `Consignee`, `Destination service`,
`Shipment mode - destination`, `Freight type`, `Incoterm`, `Incoterm location site`,
`Transportation mode`, `Booking Type`, plus `Port`.

### Next action

Click **`Edit booking`** (top right) to reach the editable page - the SKU grid from the
earlier screenshot. That is the next step.

### Notes

- This page is **read-only**. `Edit booking` is the entry point to everything the
  automation fills; `Cancel booking` must never be clicked, and sits right beside it.
  Any selector for the edit button must not be able to land on its neighbour.
- `Download PDF` exists; potentially useful for keeping a record of what was submitted,
  and worth revisiting once filling works.
- Only the structure is recorded here. The values in the screenshots come from unrelated
  POs and are not evidence of what these fields should contain.

---

---

## Step 7 — Filling the SKU grid

Reached by `Edit booking` (step 6). Three things are filled on this page before the grid:
the commercial-invoice currency, and the PO card is expanded if collapsed.

### 7a — Commercial invoice currency (header)

| Item | Detail |
|---|---|
| Selector | `data-testid="commercial-invoice-currency"` |
| Value | **`USD`, always** |
| Type | plain text input, empty on arrival |

### 7b — Expand the PO card if it is collapsed

| Item | Detail |
|---|---|
| Card | `data-testid="booking-po-sku-edit-<PO>"`, also `data-po-order-id="<PO>"` |
| PO text | `data-testid="po-sku-edit-po-number"` |
| Toggle | `data-testid="po-sku-edit-toggle-expand"`, `aria-label="Expand or collapse SKU table"` |
| Expanded body | `data-testid="po-sku-edit-expanded"` |
| Collapsed/expanded signal | chevron icon: `chevron-up` when expanded, `chevron-down` when collapsed |

**Check first, then click.** If `po-sku-edit-expanded` (or the `chevron-up` icon) is
present the card is already open and must **not** be clicked - clicking would collapse it.

### 7c — Matching our rows to portal rows

| Item | Detail |
|---|---|
| Our match key | **`PO no` + SKU core** |
| SKU core | everything before the size-suffix on both sides: `A6C3T-BC9J-XS` |
| Portal row key | `data-row-key="<PO>-<line>-<seq>"`, e.g. `4500046108-6-60` |
| Portal SKU text | `po-sku-edit-sku-cell-text` → `A6C3T-BC9J-XS-BW1 (4500046108-6-60)` |
| Suffix | **ignored.** The portal shows `BW1`, our data has whatever the packing list
  implied; the suffix is not in the source document, is generated by the portal, and is
  **never compared** |

So the match is: strip everything from the last `-` on both sides, then compare
`PO` + `A6C3T-BC9J-XS`.

### 7d — The fields filled, per matched row

All keyed by the same suffix `-<PO>-<line>-<seq>`:

| Portal field | `data-testid` | Filled from (Booking_lines) | Rule |
|---|---|---|---|
| Booked quantity | `po-sku-edit-table-book-qty-…` | `Booked quantity` | always write |
| Booked volume | `po-sku-edit-table-volume-…` | `Booked volume` | always write |
| Booked gross weight | `po-sku-edit-table-weight-…` | `Booked gross weight` | always write |
| Booked packages | `po-sku-edit-table-book-pkg-…` | `Booked packages` | always write |
| Description of goods | `po-sku-edit-table-description-…` | `Description of goods` | **only if blank** |
| Cargo type | `po-sku-edit-table-cargo-type-…` | - | **always `Flat pack`** (`FLAT_PACK`) |
| Commodity code | `po-sku-edit-table-commodity-inline-…-commodity-code-0` | - | **only if blank** |

Units are left alone: quantity `EACH`, packages `CARTON`, already set by the portal.

### 7e — Commodity code when a row is blank

The portal pre-fills commodity code. If a row's is **missing**:

1. **Copy the value from any other SKU row on the page that has one.**
2. If **no row** on the page has one, **pause and ask the user** for the missing code,
   then fill it.

This happens per row - a code recovered from another row also satisfies later blanks.

### 7f — Unmatched rows

If one of our SKUs has no matching portal row, **skip it and record it on the report with
the reason**. It is not added, not invented, not guessed at.

### Grid behaviour notes

- **The table is virtual-scrolled** (`po-sku-edit-table-vscroll-bar`, `1-17 of 17`). The
  saved page contained only 9 of 17 rows. **Never read the grid as a list** - address each
  row by its `data-row-key` and fill it where it stands.
- Row keys are `PO-line-seq` (`4500046108-6-60`), so a row can be targeted without
  scrolling to it.
- The portal's `Total quantity / Total volume / Total weight / Total packages` for a PO
  will **not** agree with our totals before filling - the portal holds the ordered lines,
  we hold what is shipping. **Bringing the portal into line with Booking_lines is the
  entire purpose of the tool.** After filling, the totals are the reconciliation check.

---

---

## Step 8 — The Review page: read, compare, submit

Reached with `Review` after the grid is filled. **Nothing is edited on this page** - it is
read only.

### 8a — What is read

Per PO, from the summary card:

| Reading | `data-testid` / label | Compare against (data sheet, `Packing_lists`) |
|---|---|---|
| Total quantity | `Total quantity (EACH)` | column **J** `Ship qty (pcs)` |
| Total packages | `Total packages (CARTON)` | column **L** `Total cartons` |
| Total weight | `Total weight (kg) (KILOGRAM)` | column **N** `Total gross wt (kg)` |
| Total volume | `Total volume (cbm) (CUBIC_METER)` | column **O** `Total CBM` |

Each value is a `review-data-label` / `review-data-value` span pair:

```html
<span class="review-data-label">Total quantity (EACH)</span>
<span class="review-data-value">1050</span>
```

**Match the label by prefix, not literally.** The page appends the unit in brackets, and
those differ between the two pages already seen:

| Page | Volume label | Weight label |
|---|---|---|
| Edit page | `Total volume (cbm)` | `Total gross weight (kg)` |
| Review page | `Total volume (cbm) (CUBIC_METER)` | `Total weight (kg) (KILOGRAM)` |

Matching on `Total volume` / `Total weight` / `Total quantity` / `Total packages` as a
prefix survives both.

### 8b — The SKU-wise comparison and the totals check

Every review row carries the same `data-row-key` as the edit page
(`booking-create-review-sku-table-4500046108` rows keyed `<PO>-<line>-<seq>`), and the
values are plain read-only text - no inputs. So each filled row is compared with the
matching `Booking_lines` row using the same PO + SKU-core match as step 7c.

**Compare rounded, not raw.** The page shows values at display precision:

| Field | Portal shows | Our value | Same value? |
|---|---|---|---|
| Volume, one row | `0.053` | `0.0528` | **yes** - 0.0528 rounded to 3 dp is 0.053 |
| Gross weight, one row | `3` | `3.00` | **yes** - same number, zero display |

So the rule is: **round our value to the portal's displayed precision, then compare.**
Volume to **3 decimals**, weight to 3, quantity and packages as whole numbers. `3` and
`3.00` are the same number and need no special handling.

**Totals are compared against the rows that were actually filled.** If a SKU of ours has
no portal row it is skipped (step 7f), so the portal total can only equal the sum of the
**matched** rows - never the sum of the whole packing list. The expected value for J/L/N/O
is therefore `sum of matched Booking_lines rows`, and the whole-list figure is not the
comparison target.

**Always re-read the totals at Review.** The same PO showed `Total volume 1.428` on the
edit page and `1.426` on the Review page, so the edit page's figure is not carried over.

### 8c — Submit

| Item | Detail |
|---|---|
| Button | `data-testid="booking-header-submit"`, `aria-label="Submit"` |
| Error count | `data-testid="booking-create-review-errors-count"` → `Errors: 0` |
| Error table | `data-testid="booking-create-review-errors-table"` |
| Do not click | `booking-header-cancel`, and `booking-header-save-draft` before a submit |

**Only when every comparison passes**: click **Submit**.

Every one of our SKUs must reach the portal before this page is even reached: a missing
line stops the run at step 7f. So by the time Review is open, the comparison is
whole-list against whole-list.

**If `Errors:` is not 0**, or any comparison fails, do not submit - record and report.

### 8d — Confirming the booking took

After submit, the flow returns to the bookings list. Then:

1. Filter by **the PO just submitted** (step 3 again).
2. Read the **Status** (step 4).
3. The booking succeeded only if the status reads **`Pending for confirmation`**
   or **`Booking confirmed`**.
4. Anything else means **the booking did not take** - record it on the report.

That ends the PO cycle; the next PO begins with `Clear filters` (step 3 decision).

---

---

## Worked example — why a missing SKU line stops the run

PO `4500046108`, our data sheet against a portal holding 9 of our 28 lines:

| | Qty | Cartons | Gross kg | Volume |
|---|---|---|---|---|
| Packing list | 1,442 | 41 | 315.09 | 2.1648 |
| Would have been booked | 540 | 14 | 114.00 | 0.741 |
| **Would never have been booked** | **902 (63%)** | **27** | **201.09** | **1.429** |

19 of 28 SKUs, 63% of the shipment by quantity, simply absent - including
`A6C3T-RCQX-M` (202 pcs, 4 cartons) and `A6C3T-RCQX-L` (170 pcs, 3 cartons).

**The portal's totals would not reveal it.** The portal totals the rows it holds, so
`Total quantity 540` looks self-consistent; only the row-wise comparison against our sheet
shows the gap.

### The rule

**If any of our SKUs has no portal row, that PO is not submitted.** The run:

1. fills the rows it could match,
2. saves a draft so no work is lost,
3. **leaves the edit page and returns to the bookings list**,
4. records `Not submitted - SKU missing`, naming every unmatched SKU,
5. **carries straight on to the next PO** - `Clear filters`, next PO, same loop.

Nothing waits for a human at this point. Review is never reached, so the Review stop
setting is irrelevant: that PO simply produces a red line on the report.

A booking that carries less than the packing list looks correct, reads as confirmed, and
the shortage surfaces later as a commercial problem. A booking that was never made is
obvious immediately. Only the second is safe to automate.

Missing rows are **never invented**: a SKU absent from the portal may be absent for a
reason (not ordered, cancelled line, wrong PO), and adding it would book goods the buyer
never asked for.

## When a selector is wrong

The filter panel and bookings list were never saved as HTML, so their selectors are the
one part of this mapping written from screenshots. When one fails:

1. The run writes a **screenshot**, the **page HTML** and the **URL** to
   `portal-failures/` beside the data sheet.
2. The error names the file path, so the failing page can be sent back and the selector
   fixed by reading its DOM instead of guessing again.

A failure on one PO is recorded as that PO's result and **the batch continues** - a
timeout on the third PO must not abandon the remaining six.

---

## Decisions taken

| Question | Decision |
|---|---|
| Which field takes the PO? | **`Order`** only. The value is the data sheet's **split PO**, copied as-is. PO formats vary (`4500036312`, `POEU450245255333`, …) so the field is located **by its label**, never by matching the number's shape. |
| Which reference fields matter? | **`Booking`, `Order`, `SKU`** in principle; **`Order` only** for now. Everything else in the panel is not required. |
| What else does the automation touch on this page? | Nothing. One PO at a time through the `Order` field - no booking-number filter, no date filter, no other field. Booking-number work may come later. |
| Moving between POs | **Click `Clear filters` first**, then run the same sequence again for the next PO. |
| One PO, several bookings | **Pause and ask.** Autobook lists the candidate bookings and waits for the buyer to pick one, then continues. Same pattern as any other mid-run checkpoint. |
| Which statuses are skipped | **`Cancel` and `Stuffed`.** Exact label match, not substring; anything else proceeds. |
| Is the PO shown in the result row? | **No** - by design. The filter result is trusted; `No bookings found` means "not found". |
| The date filter | Not part of the mapping. Never read, set or cleared. |
| The SKU suffix (`BWI` / `BW1`) | **Not compared.** Matching is `PO` + SKU core (`A6C3T-BC9J-XS`). The suffix appears nowhere in the source document and is generated by the portal. |
| Commercial invoice currency | **`USD`**, always, on the edit page header. |
| Cargo type | **`Flat pack`** (`FLAT_PACK` internally), always, no lookup. |
| Description of goods | Portal pre-fills. Fill from Booking_lines **only when blank**. |
| Commodity code | Portal pre-fills. If blank, copy from another row; if none exists, **pause and ask the user**. |
| Our SKU not present on the portal | **Stop the PO.** Fill what matches, save a draft, do not submit, report `Not submitted - SKU missing` with every unmatched SKU named. |
| Reading the grid | **Never as a list** - virtual scrolling means only some rows exist in the DOM. Address rows by `data-row-key`. |
| Review page: edits | **None.** Read, compare, then Submit. |
| Review comparison | Column J vs total quantity, L vs total packages, N vs total weight, O vs total volume, **plus** a SKU-wise row comparison. |
| Numeric comparison | **Round our value to the portal's display precision, then compare**: volume 3 dp, weight 3 dp, quantity and packages whole. `0.0528` = `0.053`, `3.00` = `3`. |
| Totals comparison target | The sum of the **matched** rows, not the whole packing list - an unmatched SKU is skipped and reported. |
| Skipped SKU and submit | A SKU with no portal row **blocks the submit**. The run fills what it can, saves a draft, stops before Review, and reports `Not submitted - SKU missing`. |
| Stop before submit | **Off by default** - a run books. `--dry-run` (CLI) or `stop_before_submit` in settings rehearses a fill without submitting. |
| When to submit | **Only when every comparison passes** and `Errors: 0`. |
| Confirming the result | Re-filter the PO and read Status: `Pending for confirmation` / `Booking confirmed` = success; anything else = not done, reported. |
| Report | A **separate tab** in the data sheet, PO-wise, listing success and errors per booking. |

### Consequence of "Order field only"

The date chip is untouched - not read, not set, not cleared. Only `Order` is used.

### The pause-and-ask interaction

When one PO matches more than one booking, Autobook must show at least the booking
number for each candidate - ideally also SKU count and status, both of which the list
already displays - and wait for a choice before continuing.

---

## Steps still to come

- [x] ~~Status `Cancel` / `Stuffed` → record and skip~~ — step 4a
- [x] ~~More than one booking → ask the user~~ — step 4b
- [x] ~~The editable page after `Edit booking`~~ — step 7, mapped from the saved page
- [x] ~~Filling the grid (one row per SKU)~~ — step 7d
- [x] ~~The Review step, and where the automation stops~~ — step 8
- [x] ~~How one PO's turn ends~~ — step 8d: re-filter, read status, then next PO
- [ ] The report tab layout (PO-wise success / error)
