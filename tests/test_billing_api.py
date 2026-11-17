import base64
import json
import os
from unittest.mock import patch

import psycopg2

from odoo.exceptions import UserError
from odoo.tests import HttpCase, TransactionCase, tagged
from odoo.tools import mute_logger

from ..controllers.main import BillingAPI
from ..services import company_service

API_ENV = {'ODOO_API_USER': 'api', 'ODOO_API_PASSWORD': 'secret'}


def _pg_error(cr, errcode):
    """A real psycopg2 error with SQLSTATE *errcode*, message 'kaputt' and a row in its DETAIL."""
    try:
        with mute_logger('odoo.sql_db'), cr.savepoint():
            cr.execute(f"DO $$ BEGIN RAISE EXCEPTION 'kaputt' USING ERRCODE = '{errcode}', "
                       "DETAIL = 'Failing row contains (geheim)'; END $$")
    except psycopg2.Error as exc:
        return exc


@tagged('post_install', '-at_install')
class TestBillingAPI(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.partner = cls.env['res.partner'].create({
            'name': 'Erika Muster', 'state_id': cls.env.ref('base.state_de_by').id,
        })

    def setUp(self):
        super().setUp()
        patcher = patch.dict(os.environ, API_ENV)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _post(self, path, payload):
        response = self.url_open(f'/api/v1/internal/{path}', data=json.dumps(payload), headers={
            'Content-Type': 'application/json',
            'Authorization': 'Basic ' + base64.b64encode(b'api:secret').decode(),
        })
        self.env.invalidate_all()
        return response.status_code, response.json()

    def _update(self, **fields):
        return self._post('partner/update', {'partner_id': self.partner.id, **fields})

    def _invoice(self, tariff_version, lines):
        return self._post('billing/create_invoice', {
            'partner_id': self.partner.id, 'tariff_version': tariff_version, 'invoice_lines': lines,
            'billing_period_start': '2026-01-01 00:00:00', 'billing_period_end': '2026-01-31 23:59:59',
        })

    def _moves(self):
        return self.env['account.move'].search_count([('partner_id', '=', self.partner.id)])

    def test_update_partner_writes_name_and_address(self):
        status, body = self._update(name='Max', surname='Muster', street='Hauptstr. 1', region='Hessen')
        self.assertEqual((status, body['success']), (200, True))
        self.assertEqual(self.partner.name, 'Max Muster')
        self.assertEqual(self.partner.street, 'Hauptstr. 1')
        self.assertEqual(self.partner.state_id, self.env.ref('base.state_de_he'))

    def test_update_partner_clears_state_on_null_region(self):
        self.assertEqual(self._update(region=None)[0], 200)
        self.assertFalse(self.partner.state_id)

    def test_update_partner_refuses_unknown_region(self):
        status, body = self._update(street='Neu 1', region='Bavaria')
        self.assertEqual((status, body['success']), (400, False))
        self.assertEqual(self.partner.state_id, self.env.ref('base.state_de_by'))
        self.assertFalse(self.partner.street)

    def test_update_partner_refuses_empty_name(self):
        self.assertEqual(self._update(name=None, surname='')[0], 400)
        self.assertEqual(self.partner.name, 'Erika Muster')

    def test_update_partner_refuses_non_integer_id(self):
        status, body = self._post('partner/update', {'partner_id': 'abc', 'name': 'X'})
        self.assertEqual((status, body['success']), (400, False))

    def test_create_partner_error_is_json(self):
        with patch.object(type(self.env['res.partner']), 'create', side_effect=RuntimeError('boom')):
            status, body = self._post('partner/create', {'email': 'neu@example.com', 'name': 'A', 'surname': 'B'})
        self.assertEqual((status, body), (500, {'success': False, 'error': 'boom'}))

    def test_database_error_answers_without_failing_row(self):
        error = _pg_error(self.env.cr, 'not_null_violation')
        with patch.object(type(self.env['res.partner']), 'create', side_effect=error):
            status, body = self._post('partner/create', {'email': 'neu@example.com', 'name': 'A', 'surname': 'B'})
        self.assertEqual((status, body['error']), (500, 'kaputt'))

    def test_create_attachment(self):
        status, body = self._post('billing/create_attachment', {
            'invoice_id': 1, 'filename': 'kosten.pdf', 'data': base64.b64encode(b'%PDF-1.4').decode(),
        })
        self.assertEqual(status, 200)
        self.assertEqual(self.env['ir.attachment'].browse(body['attachment_id']).name, 'kosten.pdf')

    def test_credit_note_resolves_19_percent_tax(self):
        status, body = self._invoice(4, [{'product_code': 'anlagen_bonus', 'quantity': 1000, 'price_unit': 0.159664, 'tax_amount': 19}])
        self.assertEqual((status, body['state']), (200, 'posted'))
        self.assertEqual(body['amount_total'], 190.0)

    def test_credit_note_returns_its_lines_as_booked(self):
        # Test user 2, 05.-11.11.2026, sent unrounded like the backend: the net 2.865 rounds up to 2.87, VAT on that.
        status, body = self._invoice(4, [
            {'product_code': 'anlagen_bonus', 'quantity': 17.94409, 'price_unit': 0.19 / 1.19, 'tax_amount': 19},
            {'type': 'section', 'name': 'Abschnitt'},
        ])
        self.assertEqual(status, 200)
        self.assertEqual(body['lines'], [{
            'product_code': 'anlagen_bonus', 'quantity': 17.944, 'price_unit': 0.159664,
            'price_subtotal': 2.87, 'price_total': 3.42,
        }])

    def _coarsen(self, precision_xmlid):
        precision = self.env.ref(precision_xmlid)
        # Restores through the ORM, which clears the cached digits; the test's rollback alone would not.
        self.addCleanup(precision.write, {'digits': precision.digits})
        precision.digits = 2

    def test_coarser_price_precision_is_refused_before_posting(self):
        self._coarsen('product.decimal_price')
        status, body = self._invoice(4, [{'product_code': 'anlagen_bonus', 'quantity': 17.944, 'price_unit': 0.159664, 'tax_amount': 19}])
        self.assertEqual(status, 500)
        self.assertIn('Position 1 (anlagen_bonus) anders buchen: Preis 0.16 statt 0.159664', body['error'])
        self.assertEqual(self._moves(), 0)

    def test_coarser_quantity_precision_is_refused_before_posting(self):
        self._coarsen('product.decimal_product_uom')
        status, body = self._invoice(4, [{'product_code': 'anlagen_bonus', 'quantity': 17.944, 'price_unit': 0.159664, 'tax_amount': 19}])
        self.assertEqual(status, 500)
        self.assertIn('Menge 17.94 statt 17.944', body['error'])
        self.assertEqual(self._moves(), 0)

    def test_replaced_tax_is_refused_before_posting(self):
        create = type(self.env['account.move']).create

        def replace_tax(moves, vals):
            invoice = create(moves, vals)
            lines = invoice.invoice_line_ids
            lines.tax_ids = lines.tax_ids.copy({'amount': 7})
            return invoice

        with patch.object(type(self.env['account.move']), 'create', autospec=True, side_effect=replace_tax):
            status, body = self._invoice(4, [{'product_code': 'anlagen_bonus', 'quantity': 1, 'price_unit': 1, 'tax_amount': 19}])
        self.assertEqual(status, 500)
        self.assertIn('Steuer 7 % exkl. statt 19 % exkl.', body['error'])
        self.assertEqual(self._moves(), 0)

    def test_community_credits_pass_the_check_as_a_credit_note(self):
        # Shaped like buildCommunityTariffInvoiceLines: unrounded negative credits, a zero self-use line kept.
        credit = {'quantity': 1, 'tax_amount': 19, 'tax_included': False}
        status, body = self._invoice(5, [
            {'type': 'section', 'name': 'Korrekturen durch Energiegemeinschaft'},
            {'product_code': 'community_purchase', 'price_unit': -1.2345675, **credit},
            {'product_code': 'savings_plant_cons', 'price_unit': 0, **credit},
            {'product_code': 'community_sale', 'price_unit': -0.4999999, **credit},
        ])
        self.assertEqual((status, body['state']), (200, 'posted'))
        self.assertEqual(self.env['account.move'].browse(body['bill_id']).move_type, 'out_refund')

    def test_concurrency_error_retries_the_request(self):
        error = _pg_error(self.env.cr, 'serialization_failure')
        create_invoice = BillingAPI._do_create_invoice
        calls = []

        def fail_once(controller, env, payload):
            calls.append(payload)
            if len(calls) == 1:
                raise error
            return create_invoice(controller, env, payload)

        with patch.object(BillingAPI, '_do_create_invoice', autospec=True, side_effect=fail_once):
            status, body = self._invoice(4, [{'product_code': 'anlagen_bonus', 'quantity': 1, 'price_unit': 1, 'tax_amount': 19}])
        self.assertEqual((status, body['state'], len(calls)), (200, 'posted', 2))
        self.assertEqual(self._moves(), 1)

    def test_failed_post_leaves_no_draft_move(self):
        created = []

        def refuse(moves):
            created.extend(moves.ids)
            raise UserError('Buchung abgelehnt')

        with patch.object(type(self.env['account.move']), 'action_post', autospec=True, side_effect=refuse):
            status, body = self._invoice(1, [{'product_code': 'grundpreis_energie_vertrag', 'quantity': 1, 'price_unit': 10}])
        self.assertEqual((status, body['error']), (500, 'Buchung abgelehnt'))
        self.assertTrue(created)
        self.assertFalse(self.env['account.move'].browse(created).exists())

    def test_missing_tax_is_refused_with_its_rate(self):
        status, body = self._invoice(4, [{'product_code': 'anlagen_bonus', 'quantity': 1, 'price_unit': 1, 'tax_amount': '7.5'}])
        self.assertEqual(status, 500)
        self.assertIn('Kein 7.5 %-Steuersatz', body['error'])
        self.assertEqual(self._moves(), 0)

    def test_tax_of_another_company_is_ignored(self):
        other = self.env['res.company'].create({'name': 'Andere GmbH', 'country_id': self.env.ref('base.de').id})
        group = self.env['account.tax.group'].create({'name': 'Fremd', 'company_id': other.id})
        self.env['account.tax'].create({
            'name': '7.5 % fremd', 'amount': 7.5, 'type_tax_use': 'sale', 'company_id': other.id, 'tax_group_id': group.id,
        })
        status, body = self._invoice(4, [{'product_code': 'anlagen_bonus', 'quantity': 1, 'price_unit': 1, 'tax_amount': 7.5}])
        self.assertEqual(status, 500)
        self.assertIn('Kein 7.5 %-Steuersatz', body['error'])


@tagged('post_install', '-at_install')
class TestCompanyService(TransactionCase):

    def test_new_company_name_configures_main_company_with_logo(self):
        environ = {'COMPANY_NAME': 'Neue Energie GmbH', 'COMPANY_LOGO_URL': 'https://example.com/logo.png'}
        with patch.dict(os.environ, environ), patch.object(company_service, '_fetch_logo', return_value=None) as fetch_logo:
            company = company_service.get_or_create_company(self.env)
        fetch_logo.assert_called_once_with('https://example.com/logo.png')
        self.assertEqual(company, self.env.ref('base.main_company'))
        self.assertEqual(company.name, 'Neue Energie GmbH')

    def test_existing_company_skips_logo_download(self):
        environ = {'COMPANY_NAME': self.env.company.name, 'COMPANY_LOGO_URL': 'https://example.com/logo.png'}
        with patch.dict(os.environ, environ), patch.object(company_service, '_fetch_logo') as fetch_logo:
            self.assertEqual(company_service.get_or_create_company(self.env), self.env.company)
        fetch_logo.assert_not_called()
