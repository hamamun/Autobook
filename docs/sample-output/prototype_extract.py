import csv, re, datetime, os
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

SRC = "/tmp/arena-coding-uploads/JMF-26-GS-3844 SEA CA.csv"

with open(SRC, newline="", encoding="utf-8-sig") as f:
    rows = list(csv.reader(f))

def cell(r, c):
    return rows[r][c].strip() if c < len(rows[r]) else ""

# ---------- header block: label at col0/col12, value 2 cells right of ':' ----------
def header_value(label, cols=(12, 0)):
    for c in cols:
        for r in range(0, 12):
            if cell(r, c).upper().replace(" ", "") == label.upper().replace(" ", ""):
                for k in range(c + 1, min(c + 8, len(rows[r]))):
                    if cell(r, k) and cell(r, k) != ":":
                        return cell(r, k)
    return ""

def header_value_right(label):
    """right-hand block: label at col12, value at col16"""
    for r in range(0, 12):
        if cell(r, 12).upper() == label.upper():
            return cell(r, 16)
    return ""

supplier   = cell(0, 0)
address    = cell(1, 0).replace("ADDRESS:", "").strip()
doc_title  = cell(2, 0)
style_no   = header_value("STYLE NO")
split_po   = header_value("SPLIT PO NO")
order_no   = header_value("ORDER NO")
description= header_value("DESCRIPTION")
order_qty  = header_value("ORDER QTY")
ship_qty   = header_value("SHIP QTY")
tot_pack   = header_value_right("TOTAL PACK QTY")
tot_qty    = header_value_right("TOTAL QUANTITY")
tot_ctn    = header_value_right("TOTAL CARTON")
net_wt     = header_value_right("TOTAL NET WEIGHT")
gross_wt   = header_value_right("TOTAL GROSS WEIGHT")
cbm        = header_value_right("TOTAL CBM")

# ORDER NO not present in the value cell -> recover from filename
fname = os.path.basename(SRC)
m = re.match(r"([A-Z]+)-(\d+)-([A-Z]+)-(\d+)\s+([A-Z]+)\s+([A-Z]+)", fname)
file_order, buyer_code, country = (m.group(4), m.group(3), m.group(6)) if m else ("", "", "")
order_no_src = "document" if order_no else ("filename" if file_order else "MISSING")
order_no = order_no or file_order

SIZES = [cell(12, c) for c in range(5, 13)]      # XXS..3XL
SIZE_COLS = list(range(5, 13))

cartons, colour = [], ""
for r in range(13, len(rows)):
    tag = cell(r, 0)
    if tag.upper().startswith(("TOTAL", "GRAND")):
        if r < 30:      # keep walking past per-colour subtotals
            continue
        break
    if not (tag.isdigit()): 
        if r > 30: break
        continue
    if cell(r, 3):
        colour = cell(r, 3)          # merged-cell forward fill
    for i, c in enumerate(SIZE_COLS):
        q = cell(r, c)
        if q and q != "0":
            cartons.append(dict(ctn=tag, colour=colour, size=SIZES[i], qty=int(float(q)),
                                per_ctn=int(float(cell(r, 13) or 0)),
                                total_pcs=int(float(cell(r, 14) or 0)),
                                nw=float(cell(r, 15) or 0), gw=float(cell(r, 16) or 0),
                                ttl_nw=float(cell(r, 17) or 0), ttl_gw=float(cell(r, 18) or 0),
                                cbm=float(cell(r, 20) or 0)))

# ---------- reconciliation ----------
checks = []
def num(v):
    v = (v or "").strip().replace(",", "")
    if v == "": return None
    try:
        f = float(v)
        return int(f) if f.is_integer() else f
    except ValueError:
        return v

def chk(name, expected, found, status):
    checks.append((name, expected, found, status))

sum_qty = sum(c["qty"] for c in cartons)
chk("Ship qty: header vs carton rows", ship_qty, sum_qty, "PASS" if str(sum_qty) == str(ship_qty) else "FAIL")
chk("Ship qty: header vs GRAND TOTAL", ship_qty, cell(29, 14), "PASS" if cell(29, 14) == str(ship_qty) else "FAIL")
chk("Ship qty: header vs summary block", ship_qty, cell(45, 13), "PASS" if cell(45, 13) == str(ship_qty) else "FAIL")
chk("Cartons: header vs GRAND TOTAL", tot_ctn, cell(29, 2), "PASS" if cell(29, 2) == str(tot_ctn) else "FAIL")
nw_sum = round(sum(c["ttl_nw"] for c in cartons), 2)
gw_sum = round(sum(c["ttl_gw"] for c in cartons), 2)
chk("Net weight: header vs line sum", net_wt, nw_sum, "PASS" if abs(float(net_wt) - nw_sum) < 0.02 else "FAIL")
chk("Gross weight: header vs line sum", gross_wt, gw_sum, "PASS" if abs(float(gross_wt) - gw_sum) < 0.02 else "FAIL")
chk("CBM: header vs line sum (3dp)", cbm, round(sum(c['cbm'] for c in cartons), 4),
    "PASS" if abs(float(cbm) - sum(c['cbm'] for c in cartons)) < 0.01 else "FAIL")
chk("ORDER NO present in document", "value in cell", order_no_src,
    "REVIEW" if order_no_src != "document" else "PASS")
chk("Total pack qty present", "value in cell Q4", "blank in source" if not tot_pack else tot_pack,
    "REVIEW" if not tot_pack else "PASS")
chk("Order qty vs ship qty (short shipment)", order_qty, ship_qty, "INFO")

for k in ("order_qty", "ship_qty", "tot_qty", "tot_ctn", "net_wt", "gross_wt", "cbm"):
    globals()[k] = num(globals()[k])

# ---------- workbook ----------
wb = Workbook()
HDR = PatternFill("solid", fgColor="1F3864")
HDR_F = Font(color="FFFFFF", bold=True, size=10)
THIN = Border(*[Side(style="thin", color="BFBFBF")] * 4)
GOOD = PatternFill("solid", fgColor="C6EFCE")
WARN = PatternFill("solid", fgColor="FFEB9C")
INFO = PatternFill("solid", fgColor="DDEBF7")

def sheet(ws, headers, data, widths=None, status_col=None):
    ws.append(headers)
    for i, h in enumerate(headers, 1):
        c = ws.cell(1, i); c.fill = HDR; c.font = HDR_F
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in data:
        ws.append(row)
    for r in ws.iter_rows(min_row=2, max_row=ws.max_row, max_col=len(headers)):
        for c in r:
            c.border = THIN
            c.font = Font(size=10)
    if status_col:
        for r in range(2, ws.max_row + 1):
            v = ws.cell(r, status_col).value
            ws.cell(r, status_col).fill = {"PASS": GOOD, "REVIEW": WARN, "INFO": INFO, "FAIL": WARN}.get(v, INFO)
    for i, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "A2"

ws = wb.active; ws.title = "1_Header"
sheet(ws, ["Field", "Value", "Source", "Confidence", "Note"], [
    ["Document type", doc_title, "row 3 col A", "high", ""],
    ["Supplier", supplier, "row 1 col A", "high", ""],
    ["Supplier address", address, "row 2 col A", "high", ""],
    ["Buyer / brand code", buyer_code, "filename", "medium", "document says GYMSHARK"],
    ["Destination country", country, "filename", "medium", ""],
    ["Order no", order_no, order_no_src, "medium" if order_no_src != "document" else "high",
     "value cell blank in file; recovered from filename JMF-26-GS-<3844> SEA CA" ],
    ["Split PO no", split_po, "row 6 col D", "high", ""],
    ["Style no", style_no, "row 5 col D", "high", ""],
    ["Description", description, "row 10 col D", "high", ""],
    ["Order qty (pcs)", order_qty, "row 7 col D", "high", ""],
    ["Ship qty (pcs)", ship_qty, "row 8 col D", "high", ""],
    ["Short ship (pcs)", int(order_qty) - int(ship_qty), "calculated", "high", "QTY(+/-) column"],
    ["Total cartons", tot_ctn, "row 6 col Q", "high", ""],
    ["Total net weight (kg)", net_wt, "row 7 col Q", "high", ""],
    ["Total gross weight (kg)", gross_wt, "row 8 col Q", "high", ""],
    ["Total CBM", cbm, "row 9 col Q", "high", ""],
    ["Total packs", tot_pack or "(blank in source)", "row 4 col Q", "low" if not tot_pack else "high",
     "value cell Q4 is empty; unit 'PACKS' present but no number" if not tot_pack else ""],
], [26, 62, 16, 12, 58], status_col=None)

ws2 = wb.create_sheet("2_Colour_Size_Qty")
agg = {}
for c in cartons:
    agg.setdefault(c["colour"], {s: 0 for s in SIZES})
    agg[c["colour"]][c["size"]] += c["qty"]
data = []
for col, sizes in agg.items():
    data.append([col] + [sizes[s] for s in SIZES] + [sum(sizes.values())])
data.append(["TOTAL"] + [sum(agg[c][s] for c in agg) for s in SIZES] + [sum(sum(v.values()) for v in agg.values())])
sheet(ws2, ["Colour"] + SIZES + ["Total pcs"], data,
      [22] + [7] * len(SIZES) + [11])
for c in ws2[ws2.max_row]:
    c.font = Font(bold=True, size=10)

ws3 = wb.create_sheet("3_Carton_Detail")
sheet(ws3, ["Carton no", "Colour", "Size", "Qty", "Per-ctn qty", "ctn_total vs per-ctn",
            "Net kg", "Gross kg", "CBM"],
      [[c["ctn"], c["colour"], c["size"], c["qty"], c["per_ctn"],
        "ok" if c["qty"] == c["per_ctn"] else f"differs: {c['total_pcs']}",
        c["ttl_nw"], c["ttl_gw"], c["cbm"]] for c in cartons],
      [11, 22, 7, 7, 12, 20, 10, 10, 9])

ws4 = wb.create_sheet("4_Checks")
sheet(ws4, ["Reconciliation rule", "Expected (header)", "Found (body)", "Status"], checks, [46, 20, 20, 12], status_col=4)

ws5 = wb.create_sheet("5_Review")
sheet(ws5, ["Field", "Problem", "What the operator does"], [
    ["Order no", "Value cell empty; only 'CA' sits in a neighbouring column",
     "Accept filename value 3844, or type the order no"],
    ["Buyer / country", "Not a labelled field on the document", "Confirm Gymshark / CA"],
    ["Total pack qty", "Q4 is empty in the source document", "Leave blank or enter the number of packs"],
    ["Colour names", "Colour written once per block (merged cells)", "Auto forward-filled — verify 2 colours"],
], [20, 62, 52])

out = "/home/user/Autobook/docs/sample-output/packing_list_extracted.xlsx"
os.makedirs(os.path.dirname(out), exist_ok=True)
wb.save(out)
print("saved", out)
print("carton rows:", len(cartons), "| ship qty:", sum(c["qty"] for c in cartons),
      "| cartons:", len({c["ctn"] for c in cartons}), "| colours:", list(agg))
for c in checks: print(c)
