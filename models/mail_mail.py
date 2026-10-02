from odoo import models

# Emails about these records may go out; everything else is stopped in ir.mail_server.send_email.
ALLOWED_MODELS = ('account.move', 'sale.order')


class MailMail(models.Model):
    _inherit = 'mail.mail'

    def _send(self, *args, **kwargs):
        allowed = self.filtered(lambda mail: mail.model in ALLOWED_MODELS)
        super(MailMail, allowed.with_context(ebere_mail_allowed=True))._send(*args, **kwargs)
        return super(MailMail, self - allowed)._send(*args, **kwargs)
