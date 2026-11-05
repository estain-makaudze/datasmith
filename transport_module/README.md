# Transport Management (Demo)

Odoo 19 demo module for a Zimbabwean passenger transport business running
minibuses (kombis) and buses. **Everything is custom** to the transport
workflow — vehicles, crew, leave — with Odoo Accounting integrated at the
posting points only.

## What it shows

- **Fleet**: custom vehicles (kombi/bus) with registration, route, usual
  driver, odometer, purchase price/date, and per-vehicle financials — total
  income and operating expenses rolled up from cash-up sheets, service costs,
  and net earnings.
- **Workshop & services**: send a vehicle to the workshop (status flips to
  In Workshop), record service expense lines (parts, labour), mark it back
  on the road — which rolls the next-service-due date/odometer onto the
  vehicle (with a "Service Due" ribbon and red highlight when overdue) —
  and post the service cost to Accounting (Dr expense accounts / Cr cash).
- **Crew**: custom drivers/conductors with national ID, licence details and
  expiries, phone, payment scheme, leave allocations and cash-up history.
  Each crew member automatically carries an accounting partner so payables
  are paid and reconciled per driver.
- **Daily cash-ups**: one sheet per vehicle per day/shift — gross takings,
  operating expenses (fuel, tollgates, rank fees, fines with mandatory
  receipt numbers), net banked. Posting a confirmed sheet creates a balanced
  journal entry (Dr Cash + Dr Expenses / Cr Transport Income), in USD or ZWG.
- **Driver payments**: configurable schemes — fixed wage, % commission on
  cash collected, or hybrid — over weekly/fortnightly/monthly periods. A
  payment run sums each crew member's cash-ups, applies the scheme,
  pro-rates the fixed wage for approved unpaid leave (6-day week), and posts
  per-driver payable lines.
- **Leave**: custom leave types (paid/unpaid, allocation-based or not),
  annual allocations with running balances, request → submit → approve
  workflow, calendar view. Approved unpaid absence feeds the wage deduction.
- **Configurable**: routes, expense types with GL accounts, payment schemes,
  leave types, journals/accounts and defaults under Configuration ▸ Settings.

## Demo setup

```bash
/opt/community/odoo19-venv/bin/python /opt/community/odoo19/odoo-bin \
  -d transport_demo --db_host=localhost --db_user=stan --db_password=esxakastan13 \
  --addons-path=/opt/community/odoo19/addons,/opt/enterprise/odoo19,/home/thir13ten/FACTORY/TRANSPORT \
  -i transport_module,account_accountant --with-demo
```

Demo data generates a full Monday–Saturday week of cash-ups relative to the
install date, so it is always fresh.

## Demo script (the pitch)

1. **Settings** (Transport ▸ Configuration ▸ Settings): pick the
   Miscellaneous journal for operations and wages, an income account for
   takings, a cash account, wage/commission expense accounts and a payable
   account. Save. Also set the expense account on each Expense Type.
2. Open a **confirmed cash-up**, hit *Post to Accounting*, open the journal
   entry from the smart button.
3. **Reporting ▸ Takings Analysis** — pivot vehicle × day, graph by route.
4. **Operations ▸ Run Driver Payments** — weekly, last week is pre-filled.
   Show fixed vs commission vs hybrid lines, the unpaid-leave deduction on
   Tafadzwa Moyo (2 days off for a funeral), and the cash-up drill-down.
5. Confirm + Post the run, open the entry, *Register Payment* on a driver's
   payable line.
6. Crew form: licence expiries, leave allocations with balances, cash-up
   smart button. Leave calendar under Crew ▸ Leave Requests.
7. Fleet ▸ Workshop & Services: open the draft gearbox job on the bus —
   *Send to Workshop* (watch the vehicle flip to In Workshop), *Back on the
   Road* with a next-service date, then *Post to Accounting*. Show the
   vehicle form: purchase price, income vs expenses vs service cost, net
   earnings, and the Service Due ribbon logic.

Not production-complete by design: statutory payroll deductions, ticketing,
fuel cards, vehicle service scheduling and mobile capture are the follow-on
pitch.
