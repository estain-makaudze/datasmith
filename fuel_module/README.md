# Fuel Stations (Demo)

Odoo 19 app for independent Zimbabwean fuel dealers running one or more
forecourts. It replaces the dip sheet and pump reconciliation book: every
shift produces a wet stock variance in litres and a cash variance per
attendant, and Odoo Accounting is touched only at the posting points.

Built task by task; see `../INDUSTRY_BRIEF.md` for the product brief.

## What it shows

- **Sites**: one record per forecourt, with a short code used on later documents,
  a wet stock tolerance, and stat buttons onto its tanks, pumps, nozzles and
  attendants.
- **Tanks**: capacity, dead stock and safe fill, each carrying its own
  **strapping chart** (dip in millimetres to litres). `dip_to_litres()`
  interpolates between chart rows, never extrapolates past the top row, and
  refuses to guess when a tank has no chart.
- **Test a Dip**: a wizard that converts a dip and shows the ullage left to the
  safe fill level. Reachable from the tank form or Wet Stock menu.
- **Pumps and nozzles**: a nozzle belongs to a pump and draws from exactly one
  tank at the same site, which is enforced. It carries the lifetime totaliser.
- **Attendants**: each one is created with an accounting partner, so a till
  shortage can later be carried against their name.
- **Fuel grades**: a flag on the product. Only flagged products can go in a tank.
- **Shifts**: the dip sheet. Pick a site and the sheet lays itself out, a row per
  nozzle opened at last night's closing reading and a row per tank opened at its
  last closing dip. Draft to Open locks the opening readings; Close demands every
  closing reading and works out both variances; Confirm needs a supervisor and
  rolls the nozzle totalisers forward. Litres sold are net of test litres, which
  cross the meter but go back in the tank. Tender records amount, currency and the
  rate the supervisor actually used. A per-attendant tab shows expected against
  declared, so a shortage carries one name.
- **Posting**: a confirmed shift posts one balanced journal entry, never silently
  and never twice. Debits each payment method's clearing account and each
  attendant's shortage against their own partner; credits fuel sales net of VAT
  and the VAT itself, carrying the tax and its tags so it reaches the tax report;
  debits cost of sales and credits fuel stock at the tank's average cost; and
  books any wet stock variance to the loss account at cost. It refuses to post an
  entry that does not balance, naming the difference.
- **Payment methods**: cash USD, cash ZiG, EcoCash, swipe, coupon, fleet docket.
  Mobile money and swipe demand a reference that can be verified later. Each
  method carries the clearing account it debits.
- **Pump prices**: effective-dated, per litre, VAT inclusive, never overwritten.
  A price carrying a site overrides the all-sites price for that site.
  `_get_price()` answers what the board said at any moment;
  `_get_price_periods()` splits a window at each change, so a shift straddling
  a price change is priced correctly on both sides.
- **Settings**: default wet stock tolerance and forecourt currency.

## Demo setup

```bash
cd zimprenuer-fuelstations
./upgrade.sh -i      # first install on fuel_demo
./upgrade.sh         # upgrade after changes
./upgrade.sh -s      # upgrade and keep the server running on http://localhost:8069
```

## Tests

```bash
/opt/community/odoo19-venv/bin/python /opt/community/odoo19/odoo-bin \
  -c fuel.conf -d fuel_demo -u fuel_module --test-tags /fuel_module --stop-after-init
```

Covers the dip conversion (exact rows, interpolation, clamping, empty tank, no
chart), chart monotonicity, the nozzle/tank site rule, attendant partners, and
pump prices (lookup either side of a change, site override, duplicate instants,
splitting a shift window across a change), and the shift (test litres, wet stock
variance against tolerance, deliveries mid-shift, undipped shifts, multi-currency
tender, attendant shortages, the close and confirm rules, counters rolling
forward, and the logged warning when a shift opens off last night's reading).

Pass `--no-http` when running tests, so an open browser tab cannot hold the run
open after the suite finishes.

## Demo script (the pitch)

Written in Task 7, once demo data exists.

Not production-complete by design: fleet credit, coupons, banking, licences,
the shop bridge and the hardware reading hook arrive in Releases 2 and 3.
