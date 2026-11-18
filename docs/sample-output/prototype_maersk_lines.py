import csv, os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

SRC = "/tmp/arena-coding-uploads/JMF-26-GS-3844 SEA CA.csv"
rows = list(csv.reader(open(SRC, newline="", encoding="utf-8-sig")))

def cell(r, c):
    return rows[r][c].strip() if c < len(rows[r]) else ""

SIZES = [cell(12, c) for c in range(5, 13)]
SIZE_COLS = list(range(5, 13))

# ---- carton lines ----
cartons, colour = [], ""
for r in range(13, len(rows)):
    tag = cell(r, 0)
    if tag.upper().startswith(("TOTAL", "GRAND")):
        if r < 30:
            continue
        break
    if not tag.isdigit():
        if r > 30:
            break
        continue
    if cell(r, 3):
        colour = cell(r, 3)
    for i, c in enumerate(SIZE_COLS):
        q = cell(r, c)
        if q and q != "0":
            cartons.append(dict(ctn=int(tag), colour=colour, size=SIZES[i],
                                qty=int(float(q)), gw=float(cell(r, 18) or 0),
                                nw=float(cell(r, 17) or 0), cbm=float(cell(r, 20) or 0)))

# ---- ordered vs shipped per colour+size from the SUMMARY block ----
ordered, cur_colour = {}, None
for r in range(32, 46):
    tag = cell(r, 3).upper()
    if cell(r, 1):
        cur_colour = cell(r, 1)
    if tag in ("ORDER QTY", "SHIP QTY") and cur_colour:
        for i, c in enumerate(SIZE_COLS):
            v = cell(r, c)
            if v:
                key = (cur_colour, SIZES[i])
                ordered.setdefault(key, {})["order" if tag == "ORDER QTY" else "ship"] = int(float(v))

# ---- carton measurements at the foot of the file ----
dims = []
for r in range(len(rows)):
    if "CTN MEASUREMENT" in cell(r, 12):
        d = (cell(r, 15), cell(r, 16), cell(r, 17))
        if all(d):
            dims.append(d)
sel_dims, sel_vol = None, None
for d in dims:
    v = round(float(d[0]) * float(d[1]) * float(d[2]) / 1_000_000, 4)
    if abs(v - 0.053) < 0.005:
        sel_dims, sel_vol = d, v

# ---- one line per colour+size ----
agg = {}
for c in cartons:
    a = agg.setdefault((c["colour"], c["size"]), dict(pkgs=0, qty=0, gw=0.0, nw=0.0, cbm=0.0))
    a["pkgs"] += 1
    a["qty"] += c["qty"]
    a["gw"] += c["gw"]
    a["nw"] += c["nw"]
    a["cbm"] += c["cbm"]

lines = []
for (col, size), a in agg.items():
    o = ordered.get((col, size), {})
    oq = o.get("order", a["qty"])
    note = "" if oq == a["qty"] else f"shipped {a['qty']} vs ordered {oq}"
    lines.append([
        f"<STYLE>-{col.split('-')[0].split(' ')[0]}-{size}-<SUFFIX>",
        oq, a["qty"], "Each", a["pkgs"], "Carton",
        round(a["qty"] / a["pkgs"]),
        sel_dims[0], sel_dims[1], sel_dims[2],
        round(a["cbm"], 4), round(a["gw"], 2),
        "", f"Ribbed Vest, {col.replace('-', ' ')}, {size}", "<cargo type>",
        "6109100018", "ARTICLES OF APPAREL AND CLOTHING ACCESSORIES", "BD", note or "OK",
    ])

# ================= workbook =================
wb = Workbook()
HDR_FILL = PatternFill("solid", fgColor="0F2A47")
HDR_FONT = Font(color="FFFFFF", bold=True, size=9)
THIN = Border(*[Side(style="thin", color="BFBFBF")] * 4)
GREEN = PatternFill("solid", fgColor="C6EFCE")
AMBER = PatternFill("solid", fgColor="FFEB9C")
RED = PatternFill("solid", fgColor="FFC7CE")
BLUE = PatternFill("solid", fgColor="DDEBF7")

def sheet(ws, headers, data, widths, status_col=None):
    ws.append(headers)
    for i, _ in enumerate(headers, 1):
        c = ws.cell(1, i)
        c.fill = HDR_FILL
        c.font = HDR_FONT
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in data:
        ws.append(row)
    for r in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(headers)):
        for c in r:
            c.border = THIN
            c.font = Font(size=9)
    if status_col:
        for r in range(2, ws.max_row + 1):
            v = str(ws.cell(r, status_col).value or "")
            if v.startswith("OK"):
                fill = GREEN
            elif v.startswith(("CHECK", "DECIDE", "LIKELY")):
                fill = AMBER
            elif v.startswith(("MISSING", "NEEDS")):
                fill = RED
            else:
                fill = BLUE
            ws.cell(r, status_col).fill = fill
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

# 1 - the grid as it appears on screen
ws1 = wb.active
ws1.title = "1_Maersk_Lines"
sheet(ws1,
      ["SKU number", "Ordered quantity", "Booked quantity", "Units (booked qty)",
       "Booked packages", "Units (booked pkg)", "Qty per package",
       "Pkg L", "Pkg W", "Pkg H", "Booked volume", "Booked gross weight",
       "Marks and numbers", "Description of goods", "Cargo type*",
       "Commodity code*", "Commodity description", "Country of origin", "Data check"],
      lines,
      [22, 9, 9, 9, 9, 9, 9, 6, 6, 6, 9, 11, 14, 42, 12, 12, 44, 9, 26],
      status_col=19)

# 2 - field-by-field mapping
mapping = [
    ["SKU number", "Style + colour code + size + order suffix", "A6C5J / BB2J / XS..3XL",
     "NEEDS MASTER", "Screenshot SKUs end in BWI and start with a code (A7B2K) that appears nowhere in the packing list. Must come from your SKU catalogue"],
    ["Ordered quantity", "SUMMARY block, ORDER QTY row", "per colour+size", "OK", ""],
    ["Booked quantity", "Carton grid size columns, summed per size", "per colour+size", "OK", ""],
    ["Units (booked qty)", "constant", "'Each' in both screenshot rows", "OK", "Fixed value"],
    ["Booked packages", "Count of carton rows for that size", "1 per row in this file", "OK", "Mix cartons => fewer packages than pieces"],
    ["Units (booked pkg)", "constant", "'Carton' in screenshot", "OK", "Dropdown"],
    ["Qty per package", "Booked quantity / booked packages", "58 / 1 = 58", "CHECK", "Screenshot row 2 shows 124 / 3 = 41 (41.33 rounded). Rule needed for mix cartons"],
    ["Pkg L / W / H", "CTN MEASUREMENT rows at the foot of the file", "60x40x22 and 60x40x30", "OK", "Two carton types exist; both blank in the screenshot rows"],
    ["Booked volume", "Sum of CBM for those cartons", "0.053 per carton", "CHECK", "Header total 0.7392 is authoritative; per-line CBM is rounded to 0.053"],
    ["Booked gross weight", "Sum of TTL G.W for those cartons", "per size", "OK", ""],
    ["Marks and numbers", "not present on the document", "-", "MISSING", "Free text, blank in screenshot; leave empty or take from the PO"],
    ["Description of goods", "product name, not derivable", "file: 'Ribbed Vest' / screenshot: 'Lift Miami Dumbbell'", "NEEDS MASTER", "A packing list does not carry the marketing product name"],
    ["Cargo type*", "rule from carton dimensions", "60x40x30 => Flat pack, 60x40x22 => Dry", "CHECK", "Screenshot is inconsistent: the 'Dry' row carries flat-pack volume (0.216 = 3 x 0.072)"],
    ["Commodity code*", "constant per product family", "6109100018", "NEEDS MASTER", "HS 6109.10 = cotton knit vests, which matches 'Ribbed Vest'. Confirm the national 10-digit suffix"],
    ["Commodity description", "constant per HS code", "ARTICLES OF APPAREL AND CLOTHING ACCESSORIES", "OK", "Tag-chip field on screen"],
    ["Country of origin", "supplier address", "Bangladesh => BD", "OK", ""],
]
ws2 = wb.create_sheet("2_Field_Map")
sheet(ws2, ["Field on screen", "Source", "Value / rule", "Status", "Note"], mapping,
      [24, 38, 40, 15, 66], status_col=4)

# 3 - gaps to close before a run is possible
gaps = [
    ["SKU catalogue", "MISSING", "Every SKU code as it exists in SCP (A7B2K-BB2J-3XL-BWI), one row per style+colour+size.",
     "Export from SCP or your ERP. Without it no line can be matched - this is the single blocker."],
    ["Product description", "MISSING", "The text typed into Description of goods, per SKU.",
     "Usually lives with the SKU catalogue."],
    ["HS / commodity code", "LIKELY CONSTANT", "6109100018 for cotton knit apparel.",
     "Confirm whether it varies by product family. Store in master data, not in code."],
    ["Cargo type rule", "DECIDE", "Which dimensions mean Flat pack and which mean Dry.",
     "Screenshot contradicts itself (Dry row with flat-pack volume). Agree the rule first."],
    ["Booked vs ordered qty", "DECIDE", "This file ships 269 of 306 ordered; M/Black ships 58 vs 56 ordered.",
     "Pick one for Booked quantity and show the delta. Do not let the tool hide a short shipment."],
    ["Qty per package rounding", "DECIDE", "124 pcs across 3 cartons shows as 41 on screen.",
     "Confirm the rounding the site expects and whether it must reconcile to line totals."],
    ["Order to booking link", "DECIDE", "Packing list order 3844 vs SCP booking SBK0005269571.",
     "How does an order find its booking - PO number, booking ref, or operator selection?"],
]
ws3 = wb.create_sheet("3_Gaps")
sheet(ws3, ["Item", "Status", "What it is", "Action"], gaps, [22, 16, 62, 70], status_col=2)

# 4 - the wizard, step by step
steps = [
    ["1", "Log in to Maersk SCP", "SSO or username+password, possibly MFA",
     "Human signs in once in the visible browser; session reused via storage_state. MFA stays with the human."],
    ["2", "Go to Order management > Bookings", "Left nav: Cases, Shipments, Documents, Export, Import",
     "Direct URL to the booking list, then search by PO or booking reference"],
    ["3", "Select or create the booking", "The screenshot is an EDIT page with status 'Booking confirmed'",
     "Prefer creating a NEW booking. Editing a confirmed one is an amendment - different risk, possibly chargeable."],
    ["4", "Step 1: Choose SKUs", "Paged picker '1-10 of 97' with a checkbox per row",
     "Search each SKU and tick it. The least predictable step - needs a screenshot of this screen before the design is frozen."],
    ["5", "Step 2: Booking details", "This screenshot: 6 input groups per row, rows paged 1-10 of 97",
     "Fill cell by cell, commit each with Tab (React grids often drop keystrokes otherwise), then read every field back."],
    ["6", "Verify inside the site", "Grid toolbar has an Export icon",
     "Download the site's own export and reconcile it against our computed lines before moving to Review."],
    ["7", "Step 3: Review > submit", "Review button, then confirmation",
     "Operator sign-off or automatic with a run cap. Capture the confirmation reference."],
    ["8", "Evidence", "Booking ref, screenshots, grid export",
     "Write ref, timestamps, export and screenshots into the audit trail (SQLite plus Excel export)."],
]
ws4 = wb.create_sheet("4_Wizard_Steps")
sheet(ws4, ["#", "Step", "What it looks like", "Automation approach"], steps, [5, 32, 50, 78])

# 5 - reconciliation of this file
qty_sum = sum(l[2] for l in lines)
pkg_sum = sum(l[4] for l in lines)
vol_sum = round(sum(l[10] for l in lines), 4)
gw_sum = round(sum(l[11] for l in lines), 2)
short = sum(1 for l in lines if l[18] != "OK")
checks = [
    ["Sum of booked quantity", 269, qty_sum, "OK" if qty_sum == 269 else "CHECK"],
    ["Sum of booked packages", 14, pkg_sum, "OK" if pkg_sum == 14 else "CHECK"],
    ["Sum of booked volume", 0.7392, vol_sum, "CHECK"],
    ["Sum of gross weight", 51.60, gw_sum, "OK" if abs(gw_sum - 51.6) < 0.05 else "CHECK"],
    ["SKU lines (grid holds up to 97)", "<= 97", len(lines), "OK" if len(lines) <= 97 else "CHECK"],
    ["Lines where shipped != ordered", 0, short, "CHECK" if short else "OK"],
]
ws5 = wb.create_sheet("5_Checks")
sheet(ws5, ["Check", "Expected from document", "Computed lines", "Status"], checks,
      [34, 24, 20, 12], status_col=4)

out = "/home/user/Autobook/docs/sample-output/maersk_booking_lines.xlsx"
os.makedirs(os.path.dirname(out), exist_ok=True)
wb.save(out)
print("saved", out)
print("lines:", len(lines), "qty:", qty_sum, "pkgs:", pkg_sum, "vol:", vol_sum, "gw:", gw_sum)
print("dims:", dims, "selected:", sel_dims, sel_vol)
for l in lines:
    print(l[:7], l[18])
