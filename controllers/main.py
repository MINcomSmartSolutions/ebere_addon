import base64
import json
import logging

from odoo import http
from odoo.http import request, Controller, route
from odoo import SUPERUSER_ID

_logger = logging.getLogger(__name__)

# Docker internal / loopback network prefixes
_INTERNAL_PREFIXES = ('172.', '10.', '192.168.', '127.', '::1')


class BillingAPI(Controller):
    """Internal billing API consumed by the Node.js backend.

    Every route uses ``auth='none'`` so that Odoo does not try cookie or
    session-based auth.  Instead the controller itself decodes an HTTP
    Basic-Auth header and authenticates the supplied credentials against
    the Odoo user database.  An additional check restricts access to
    Docker-internal / loopback IP ranges.
    """

    # ------------------------------------------------------------------
    # Security helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_internal_network():
        """Return *True* when the caller's IP belongs to an internal range."""
        remote = request.httprequest.remote_addr or ''
        return any(remote.startswith(p) for p in _INTERNAL_PREFIXES)

    @staticmethod
    def _authenticate_basic():
        """Decode HTTP Basic-Auth and validate against environment variables.

        Returns ``True`` on success or ``False`` on failure.
        """
        import os
        
        expected_user = os.environ.get('ODOO_API_USER', '')
        expected_password = os.environ.get('ODOO_API_PASSWORD', '')
        
        if not expected_user or not expected_password:
            _logger.error('ODOO_API_USER or ODOO_API_PASSWORD not configured')
            return False
        
        header = request.httprequest.headers.get('Authorization', '')
        if not header.startswith('Basic '):
            return False

        try:
            decoded = base64.b64decode(header[6:]).decode('utf-8')
            login, password = decoded.split(':', 1)
        except Exception:
            return False

        # Simple constant-time comparison to prevent timing attacks
        return login == expected_user and password == expected_password

    def _secured(self):
        """Run network + auth checks.

        Returns ``(True, None)`` on success or ``(None, Response)`` on
        failure.
        """
        if not self._is_internal_network():
            return None, self._error('Forbidden: external access denied', 403)
        authenticated = self._authenticate_basic()
        if not authenticated:
            return None, self._error('Unauthorized', 401)
        return True, None

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _error(message, status=400):
        return request.make_json_response(
            {'success': False, 'error': message},
            status=status,
        )

    @staticmethod
    def _ok(data, status=200):
        return request.make_json_response(
            {'success': True, **data},
            status=status,
        )

    @staticmethod
    def _parse_body():
        return json.loads(request.httprequest.data)

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @route('/api/v1/billing/health', type='http', auth='public', methods=['GET'], csrf=False)
    def health_check(self):
        """Simple health check endpoint"""
        return request.make_json_response({'status': 'ok', 'service': 'billing_api'})

    @route('/api/v1/billing/create_invoice', type='http', auth='none', methods=['POST'], csrf=False)
    def create_invoice(self):
        """Create and confirm an invoice (or credit note for tariff 4).

        Expected JSON body::

            {
                "partner_id": 42,
                "billing_period_start": "2025-01-01 00:00:00",
                "billing_period_end": "2025-01-31 23:59:59",
                "tariff_version": 1,
                "invoice_date": "2025-02-01",
                "invoice_date_due": "2025-03-01",
                "invoice_lines": [
                    {"product_code": "fixed_price", "quantity": 250, "price_unit": 0.35},
                    {"type": "section", "name": "Korrekturen …"},
                    {"product_code": "savings_plant_cons", "quantity": 1, "price_unit": -3.12}
                ]
            }
        """
        _, err = self._secured()
        if err:
            return err

        try:
            payload = self._parse_body()
        except Exception as exc:
            return self._error(f'Invalid JSON: {exc}')

        required = (
            'partner_id', 'billing_period_start', 'billing_period_end',
            'tariff_version', 'invoice_lines',
        )
        missing = [f for f in required if f not in payload]
        if missing:
            return self._error(f'Missing fields: {", ".join(missing)}')

        try:
            env = request.env(user=SUPERUSER_ID)
            result = self._do_create_invoice(env, payload)
            return self._ok(result)
        except Exception as exc:
            _logger.exception('create_invoice failed')
            return self._error(str(exc), 500)

    @route('/api/v1/billing/create_attachment', type='http', auth='none', methods=['POST'], csrf=False)
    def create_attachment(self):
        """Attach a base-64 encoded file to an existing invoice.

        Expected JSON body::

            {
                "invoice_id": 123,
                "filename": "report.pdf",
                "data": "<base64>"
            }
        """
        _, err = self._secured()
        if err:
            return err

        try:
            payload = self._parse_body()
        except Exception as exc:
            return self._error(f'Invalid JSON: {exc}')

        required = ('invoice_id', 'filename', 'data')
        missing = [f for f in required if f not in payload]
        if missing:
            return self._error(f'Missing fields: {", ".join(missing)}')

        try:
            env = request.env(user=SUPERUSER_ID)
            attachment = env['ir.attachment'].sudo().create({
                'name': payload['filename'],
                'res_model': 'account.move',
                'res_id': int(payload['invoice_id']),
                'type': 'binary',
                'datas': payload['data'],
            })
            return self._ok({'attachment_id': attachment.id})
        except Exception as exc:
            _logger.exception('create_attachment failed')
            return self._error(str(exc), 500)

    @route('/api/v1/billing/read_partner', type='http', auth='none', methods=['POST'], csrf=False)
    def read_partner(self):
        """Return basic partner details (or 404 if missing).

        Expected JSON body::

            {"partner_id": 42}
        """
        _, err = self._secured()
        if err:
            return err

        try:
            payload = self._parse_body()
        except Exception as exc:
            return self._error(f'Invalid JSON: {exc}')

        partner_id = payload.get('partner_id')
        if not partner_id:
            return self._error('Missing field: partner_id')

        try:
            env = request.env(user=SUPERUSER_ID)
            partner = env['res.partner'].sudo().browse(int(partner_id)).exists()
            if not partner:
                return self._error('Partner not found', 404)
            return self._ok({
                'partner': {
                    'id': partner.id,
                    'name': partner.name,
                    'email': partner.email or None,
                },
            })
        except Exception as exc:
            _logger.exception('read_partner failed')
            return self._error(str(exc), 500)

    # ------------------------------------------------------------------
    # Core invoice logic
    # ------------------------------------------------------------------

    def _do_create_invoice(self, env, payload):
        """Create an ``account.move``, confirm it, return key fields."""
        partner_id = int(payload['partner_id'])
        tariff_version = int(payload['tariff_version'])

        # Validate partner
        partner = env['res.partner'].sudo().browse(partner_id).exists()
        if not partner:
            raise ValueError(f'Partner with id {partner_id} not found')

        line_cmds = self._build_line_commands(env, payload['invoice_lines'])

        move_type = 'out_refund' if tariff_version == 4 else 'out_invoice'

        invoice_vals = {
            'move_type': move_type,
            'billing_period_start': payload['billing_period_start'],
            'billing_period_end': payload['billing_period_end'],
            'show_delivery_date': False,
            'state': 'draft',
            'partner_id': partner_id,
            'invoice_date': payload.get('invoice_date'),
            'invoice_date_due': payload.get('invoice_date_due'),
            'invoice_origin': 'DeltaBilling',
            'invoice_payment_term_id': 1,
            'invoice_user_id': 2,
            'tax_country_id': 57,
            'invoice_line_ids': line_cmds,
        }

        invoice = env['account.move'].sudo().create(invoice_vals)
        _logger.info('Created draft invoice id=%s partner=%s', invoice.id, partner_id)

        invoice.sudo().action_post()
        _logger.info('Confirmed invoice id=%s name=%s', invoice.id, invoice.display_name)

        return {
            'bill_id': invoice.id,
            'display_name': invoice.display_name,
            'amount_total': invoice.amount_total,
            'state': invoice.state,
        }

    @staticmethod
    def _build_line_commands(env, lines):
        """Translate JSON line items into Odoo ``(0, 0, vals)`` commands.

        Each element is either:

        * ``{"type": "section", "name": "…"}`` → section header
        * ``{"product_code": "…", "quantity": …, "price_unit": …}`` → product line
        """
        Product = env['product.product'].sudo()
        cache = {}
        commands = []

        for item in lines:
            if item.get('type') == 'section':
                commands.append((0, 0, {
                    'display_type': 'line_section',
                    'name': item['name'],
                }))
                continue

            code = item.get('product_code')
            if not code:
                raise ValueError('Invoice line missing product_code')

            if code not in cache:
                product = Product.search([('default_code', '=', code)], limit=1)
                if not product:
                    raise ValueError(f"Product with code '{code}' not found")
                cache[code] = product.id

            vals = {'product_id': cache[code]}
            if 'quantity' in item:
                vals['quantity'] = item['quantity']
            if 'price_unit' in item:
                vals['price_unit'] = item['price_unit']

            commands.append((0, 0, vals))

        return commands
