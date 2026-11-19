# Mapping the data sheet to the Maersk booking-details grid

Source: the `Booking_lines` tab of the data sheet. One row there ⇄ one row on the portal.

## The core difference: cartons vs SKUs

The packing list is organised by **carton**; the portal is organised by **SKU**, and a SKU
is `style-colour-size-suffix`. Several cartons of the same size collapse into one portal
row:

| Packing list (carton lines) | | Portal (one SKU row) |
|---|---|---|
| carton 2 — S — 65 pcs — 1 ctn — 12.60 kg | → | **A6C3T-BC9J-S-BWI** |
| carton 3 — S — 37 pcs — 1 ctn — 7.40 kg | | 102 pcs, 2 packages, 51 qty/pkg, 20.00 kg |

Autobook does this in `autobook/booking.py` and writes the result to `Booking_lines`.
Verified against the live portal screenshot: `A6C3T-BC9J-XL-BWI`, 15 pcs, 4.1 kg.

## Field by field

| Portal field | Source | Rule |
|---|---|---|
| **SKU number** | style no + colour code + size + suffix | `A6C3T` + `BC9J` + `XL` + `BWI`. `BWI` defaults automatically (`DEFAULT_SKU_SUFFIX`) because it appears in no packing list |
| **PO no** | Split PO no | The second half of the mapping key. The separate order number is not used for matching |
| **Ordered quantity** | packing list order qty (per document) | Read from the document's ORDER QTY / summary block |
| **Booked quantity** | sum of every carton of that size | The figure that must equal the shipped total |
| **Units (booked quantity)\*** | constant | `Each` |
| **Booked packages** | sum of CTN QTY for that size | Counted once per source row |
| **Units (booked packages)** | constant | `Carton` |
| **Qty per package** | booked qty ÷ booked packages | Integer, rounded down; flagged when uneven (124 ÷ 3 showed as 41) |
| **Booked Volume\*** | **column I (`CBM`) of the carton lines, added across the SKU** | Each line already carries the volume of the cartons it covers (a 6-carton line shows 0.3168). No recalculation is applied; `4500046108` reconciles to the packing list's 2.1648 |
| **Booked gross weight** | sum of TTL G.W for those cartons | 2 dp |
| **Marks and numbers** | not on a packing list | Leave blank, or supply per booking |
| **Description of goods** | description + colour + size | `Power Washed Cut Off Tank, BC9J-GS BLACK/Wash, XL` |
| **Cargo type\*** | rule from carton dimensions | **Not yet settled** — see below |
| **Commodity code\*** | constant per product family | `610910` / `6109100018` (HS 6109.10 = cotton knit) |
| **Commodity description** | constant per code | `ARTICLES OF APPAREL AND CLOTHING ACCESSORIES` |
| **Country/region of origin\*** | supplier address | `BD` |
| **Package length / width / height** | carton measurement rows | Both dimensions AND the cargo type must be resolved before these are written |

## Two things the data proves

**1. Volume in column I already accounts for carton count.** A line covering 6 cartons
carries `0.3168` (6 × 0.0528); a 2-carton line carries `0.1056`. No multiplication is
needed — but the values must still be **added together** for the lines that share a SKU.

Proof on `4500046108`: 37 carton lines → 28 SKU rows.

| Rule | Total CBM |
|---|---|
| Sum column I across each SKU's lines | **2.1648** ← matches the packing list |
| Copy one line per SKU, no summing | 1.6896 (short by 0.4752) |

The `Booking_lines` sheet carries a `Volume from cartons` column showing the addition
(e.g. `0.1056 + 0.0528`), so the figure can be checked against the source at a glance.

**2. Carton dimensions differ within one booking.** `4500046108` has cartons of both
`0.0528` and `0.0630` CBM, and 4 of its rows have no measurement at all. The booking is a
mix of carton sizes — so a single fixed L×W×H would be wrong.

## How a sheet is recognised as a packing list

Either route is enough:

1. the words `PACKING LIST` appear in the top 5 rows, **and** one of `CTN NO`,
   `STYLE NO`, `SPLIT PO NO` exists somewhere in the sheet; or
2. one header row carries `CTN NO`, `CTN QTY`, `N.W` **and** `G.W` together (the
   structural signature), which works when the title is missing.

Everything else - cover tabs, notes tabs, hidden tabs - is excluded from the data and
listed on the About tab only.

## Fields that must be filled before the portal will accept a row

The booking grid marks four fields with a red asterisk (`Units (booked quantity)`,
`Booked volume`, `Cargo type`, `Commodity code`). Operationally five values have to be
right, and each maps to a column on the data sheet:

| Portal field | Booking_lines column | Source |
|---|---|---|
| SKU number | `SKU number` | style + colour code + size + `BWI` |
| Booked quantity | `Booked quantity` | shipped qty |
| Booked volume | `Booked volume` | CBM from the carton lines |
| Booked packages | `Booked packages` | cartons from the source row |
| Booked gross weight | `Booked gross weight` | gross weight |

**Blank or zero is a failure.** A missing value leaves the cell red (`FFC7CE`) and
prefixes the row's Notes with `MISSING - cannot book until filled: <fields>`; zero is
treated exactly like blank because the portal would reject it the same way.

## Fixed values written on every row

Three fields are the same on every booking line, so a run needs no extra input:

| Column | Heading | Value | Why |
|---|---|---|---|
| O | `Cargo type` | `Flat pack` | the portal dropdown has one value in this operation; `Dry`, `None` or blank is coerced, never copied |
| P | `Commodity code` | blank | the portal pre-fills it and there is no fixed code for us to state |
| Q | `Country of origin` | `BD` | always Bangladesh; written so the operator can check it against the page |

Only `country_of_origin` is configurable (`settings.json`, or
`scripts/run_prepare.py --country-of-origin`). Cargo type is a constant and the commodity
code is deliberately never written.

## What is still undecided

**Cargo type.** The portal has two rows with identical per-carton volume (0.072) but
different cargo types (`Flat pack`, `Dry`). Two possibilities:

- it tracks carton *configuration* (flat-packed versus standing), which the packing list
  does not say; or
- it was simply set by hand and is inconsistent.

Either way it cannot be derived from the documents as they stand. Meanwhile the packing
lists themselves show two carton volumes (0.0528 and 0.0630) and some rows with none.

**Recommendation:** add one column to the packing list profile mapping — a per-supplier
carton-dimension table (volume → L, W, H, cargo type) — and have the tool fill L/W/H and
cargo type from the carton's own volume. That handles the mix correctly and removes the
guesswork. It needs your confirmation of the actual dimensions, which the documents only
give for one carton type in the sample.

## Missing master data

Three portal values exist nowhere in a packing list and must come from configuration:

| Value | Where it should live |
|---|---|
| SKU suffix (`BWI`) | settings (`sku_suffix`) |
| Commodity code | settings (`commodity_code`) |
| Country of origin | settings (`country_of_origin`), defaulted from the supplier address |
