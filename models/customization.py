from odoo import models, fields, api
from odoo.tools import format_date


class AccountMove(models.Model):
    _inherit = 'account.move'

    # All dates are stored in UTC and formatted on the client side
    billing_period_start = fields.Datetime(string='BillingPeriodStart')
    billing_period_end = fields.Datetime(string='BillingPeriodEnd')

    # Customer / contract identifiers shown in the information_block
    customer_number = fields.Char(string='Kundennummer')
    contract_number = fields.Char(string='Vertragsnummer')
    meter_point = fields.Char(string='Zählpunkt Verbraucher')

    @api.depends('name', 'invoice_date', 'invoice_date_due', 'invoice_incoterm_id',
                 'incoterm_location', 'delivery_date', 'invoice_origin', 'ref',
                 'partner_id', 'customer_number', 'contract_number', 'meter_point')
    def _compute_l10n_din5008_template_data(self):
        """Extend the DIN5008 information block with Kundennummer,
        Vertragsnummer and Zählpunkt Verbraucher."""
        super()._compute_l10n_din5008_template_data()
        for record in self:
            data = list(record.l10n_din5008_template_data or [])
            if record.customer_number:
                data.append(('Kundennummer', record.customer_number))
            if record.contract_number:
                data.append(('Vertragsnummer', record.contract_number))
            if record.meter_point:
                data.append(('Zählpunkt Verbraucher', record.meter_point))
            record.l10n_din5008_template_data = data
