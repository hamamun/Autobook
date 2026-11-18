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
| **SKU number** | style no + colour code + size + suffix | `A6C3T` + `BC9J` + `XL` + `BWI`. Suffix is site config (`sku_suffix`), it appears in no packing list |
| **Ordered quantity** | packing list order qty (per document) | Read from the document's ORDER QTY / summary block |
| **Booked quantity** | sum of every carton of that size | The figure that must equal the shipped total |
| **Units (booked quantity)\*** | constant | `Each` |
| **Booked packages** | sum of CTN QTY for that size | Counted once per source row |
| **Units (booked packages)** | constant | `Carton` |
| **Qty per package** | booked qty ÷ booked packages | Integer, rounded down; flagged when uneven (124 ÷ 3 showed as 41) |
| **Booked Volume\*** | **sum of each carton's CBM** | A line covering 6 cartons is 6 × 0.0528 = 0.3168, not 0.0528 |
| **Booked gross weight** | sum of TTL G.W for those cartons | 2 dp |
| **Marks and numbers** | not on a packing list | Leave blank, or supply per booking |
| **Description of goods** | description + colour + size | `Power Washed Cut Off Tank, BC9J-GS BLACK/Wash, XL` |
| **Cargo type\*** | rule from carton dimensions | **Not yet settled** — see below |
| **Commodity code\*** | constant per product family | `610910` / `6109100018` (HS 6109.10 = cotton knit) |
| **Commodity description** | constant per code | `ARTICLES OF APPAREL AND CLOTHING ACCESSORIES` |
| **Country/region of origin\*** | supplier address | `BD` |
| **Package length / width / height** | carton measurement rows | Both dimensions AND the cargo type must be resolved before these are written |

## Two things the data proves

**1. Volume is per carton, not per line.** The 6-carton line carries `0.3168`, and the
2-carton lines carry `0.1056`. So a portal line must sum CBM across all its cartons.

**2. Carton dimensions differ within one booking.** `4500046108` has cartons of both
`0.0528` and `0.0630` CBM, and 4 of its rows have no measurement at all. The booking is a
mix of carton sizes — so a single fixed L×W×H would be wrong.

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
