# -*- coding: utf-8 -*-
"""Demo-data generator.

Called from demo/demo_cashups.xml at install time so the demo week is always
the last complete Monday-to-Saturday relative to the install date, instead of
hard-coded dates that go stale.
"""
import logging
import random
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class TransportCashupDemo(models.Model):
    _inherit = 'transport.cashup'

    @api.model
    def _generate_demo_data(self):
        if self.search_count([], limit=1):
            return  # already generated (e.g. module update with demo)
        rng = random.Random(42)
        ref = self.env.ref

        today = fields.Date.context_today(self)
        last_sunday = today - timedelta(days=today.weekday() + 1)
        monday = last_sunday - timedelta(days=6)
        week_days = [monday + timedelta(days=i) for i in range(6)]  # Mon–Sat

        usd = self.env.company.currency_id
        zwg = ref('transport_module.currency_zwg', raise_if_not_found=False) or usd

        fuel = ref('transport_module.expense_type_fuel')
        rank = ref('transport_module.expense_type_rank_fees')
        toll = ref('transport_module.expense_type_tollgate')
        fine = ref('transport_module.expense_type_police_fine')
        wash = ref('transport_module.expense_type_car_wash')

        # (vehicle, driver, conductor, typical daily gross in USD, runs on day?)
        plan = [
            ('vehicle_kombi_1', 'driver_tafadzwa', 'conductor_rumbi', 95.0,
             lambda d: True),
            ('vehicle_kombi_2', 'driver_blessing', 'conductor_takunda', 120.0,
             lambda d: True),
            ('vehicle_kombi_3', 'driver_simba', False, 105.0,
             lambda d: True),
            ('vehicle_kombi_4', 'driver_tinashe', False, 90.0,
             lambda d: d.weekday() != 3),        # off Thursdays
            ('vehicle_bus_1', 'driver_farai', 'conductor_rumbi', 620.0,
             lambda d: d.weekday() in (0, 2, 4)),  # Mon/Wed/Fri long haul
        ]

        # Tafadzwa is off on unpaid leave Thu+Fri — no cash-ups those days,
        # and the payment run shows the pro-rata wage deduction.
        leave_days = {week_days[3], week_days[4]}

        sheets = self.browse()
        for vehicle_xml, driver_xml, conductor_xml, typical, runs_on in plan:
            vehicle = ref('transport_module.%s' % vehicle_xml)
            driver = ref('transport_module.%s' % driver_xml)
            conductor = (ref('transport_module.%s' % conductor_xml)
                         if conductor_xml else False)
            for day in week_days:
                if not runs_on(day):
                    continue
                if driver_xml == 'driver_tafadzwa' and day in leave_days:
                    continue
                # Kombi 2 banks in ZWG on Tue/Thu; everything else in USD.
                use_zwg = (zwg != usd and vehicle_xml == 'vehicle_kombi_2'
                           and day.weekday() in (1, 3))
                factor = 26.85 if use_zwg else 1.0
                gross = round(typical * rng.uniform(0.8, 1.2) * factor, 2)

                expenses = [
                    (0, 0, {'expense_type_id': fuel.id,
                            'description': 'Diesel',
                            'amount': round(gross * rng.uniform(0.18, 0.25), 2)}),
                    (0, 0, {'expense_type_id': rank.id,
                            'description': 'Rank marshal fees',
                            'amount': round(3.0 * factor, 2)}),
                ]
                if vehicle_xml == 'vehicle_bus_1':
                    expenses.append((0, 0, {
                        'expense_type_id': toll.id,
                        'description': 'ZINARA tollgates',
                        'reference': 'TG-%s%02d' % (day.strftime('%d%m'),
                                                    rng.randint(10, 99)),
                        'amount': round(12.0 * factor, 2)}))
                if rng.random() < 0.12:
                    expenses.append((0, 0, {
                        'expense_type_id': fine.id,
                        'description': 'Spot fine – pirating rank',
                        'reference': 'ZRP-%06d' % rng.randint(100000, 999999),
                        'amount': round(15.0 * factor, 2)}))
                if day.weekday() == 5 and rng.random() < 0.6:
                    expenses.append((0, 0, {
                        'expense_type_id': wash.id,
                        'description': 'Weekend car wash',
                        'amount': round(2.0 * factor, 2)}))

                sheets |= self.create({
                    'date': day,
                    'shift': 'full_day',
                    'vehicle_id': vehicle.id,
                    'route_id': vehicle.route_id.id,
                    'driver_id': driver.id,
                    'conductor_id': conductor.id if conductor else False,
                    'currency_id': zwg.id if use_zwg else usd.id,
                    'trips_count': rng.randint(6, 14),
                    'gross_takings': gross,
                    'expense_line_ids': expenses,
                })

        # Confirm everything except a couple left in draft for the demo.
        draft_sheets = sheets[-2:]
        (sheets - draft_sheets).action_confirm()

        self._generate_demo_leave(week_days)
        self._generate_demo_services(week_days)

    @api.model
    def _generate_demo_leave(self, week_days):
        """Annual-leave allocations for the crew plus one approved unpaid
        absence inside the demo week."""
        ref = self.env.ref
        annual = ref('transport_module.leave_type_annual')
        unpaid = ref('transport_module.leave_type_unpaid')
        crew = self.env['transport.driver'].search([])
        Allocation = self.env['transport.leave.allocation']
        year = week_days[0].year
        for member in crew:
            Allocation.create({
                'driver_id': member.id,
                'leave_type_id': annual.id,
                'year': year,
                'days_allocated': annual.default_annual_days or 10,
            })
        leave = self.env['transport.leave'].create({
            'driver_id': ref('transport_module.driver_tafadzwa').id,
            'leave_type_id': unpaid.id,
            'date_from': week_days[3],
            'date_to': week_days[4],
            'reason': 'Family funeral in Masvingo',
        })
        leave.action_submit()
        leave.action_approve()

    @api.model
    def _generate_demo_services(self, week_days):
        """One completed workshop service in the recent past (with a next
        service due date) plus one still-open draft to complete on stage."""
        ref = self.env.ref
        Service = self.env['transport.vehicle.service']
        svc_type = ref('transport_module.expense_type_service')
        labour = ref('transport_module.expense_type_labour')
        monday = week_days[0]

        kombi_3 = ref('transport_module.vehicle_kombi_3')
        done = Service.create({
            'vehicle_id': kombi_3.id,
            'description': 'Full service – oil, filters, front brake pads',
            'workshop_name': 'Mbudzi Motors',
            'date_sent': monday - timedelta(days=16),
            'odometer': kombi_3.current_odometer - 2400,
            'next_service_date': monday + timedelta(days=44),
            'next_service_odometer': kombi_3.current_odometer + 7500,
            'line_ids': [
                (0, 0, {'expense_type_id': svc_type.id,
                        'description': 'Oil, oil & air filters',
                        'reference': 'INV-20443', 'amount': 85.00}),
                (0, 0, {'expense_type_id': svc_type.id,
                        'description': 'Front brake pads',
                        'reference': 'INV-20443', 'amount': 60.00}),
                (0, 0, {'expense_type_id': labour.id,
                        'description': 'Workshop labour', 'amount': 40.00}),
            ],
        })
        done.action_send()
        done.date_returned = monday - timedelta(days=14)
        done.action_done()

        # Draft service on the bus, ready to send/complete live in the demo.
        bus = ref('transport_module.vehicle_bus_1')
        Service.create({
            'vehicle_id': bus.id,
            'description': 'Gearbox oil leak – inspect and reseal',
            'workshop_name': 'Harare Truck & Bus',
            'date_sent': fields.Date.context_today(self),
            'odometer': bus.current_odometer,
            'line_ids': [
                (0, 0, {'expense_type_id': svc_type.id,
                        'description': 'Gearbox seal kit', 'amount': 120.00}),
                (0, 0, {'expense_type_id': labour.id,
                        'description': 'Strip & reseal labour',
                        'amount': 150.00}),
            ],
        })
