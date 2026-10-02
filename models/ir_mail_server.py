import re

from odoo import models
from odoo.addons.base.models.ir_mail_server import MailDeliveryException
from odoo.tools import file_open

# Matches both the relative src in templates and the absolute one produced by _replace_local_links.
MODULE_IMAGE_SRC = re.compile(r'src="[^"]*?/ebere_addon/static/src/img/([\w-]+\.png)"')


class IrMailServer(models.Model):
    _inherit = 'ir.mail_server'

    def build_email(self, *args, **kwargs):
        """Embed this module's images as inline CID parts instead of remote URLs.

        Remote images depend on web.base.url being publicly reachable and are
        blocked by default in e.g. Outlook desktop; inline parts are not.
        """
        message = super().build_email(*args, **kwargs)
        html_part = message.get_body(('html',))
        if html_part is None:
            return message
        html = html_part.get_content()
        names = sorted(set(MODULE_IMAGE_SRC.findall(html)))
        if not names:
            return message
        html_part.set_content(MODULE_IMAGE_SRC.sub(r'src="cid:\1"', html), subtype='html', charset='utf-8')
        for name in names:
            with file_open(f'ebere_addon/static/src/img/{name}', 'rb') as image:
                html_part.add_related(image.read(), 'image', 'png', cid=f'<{name}>', filename=name)
        return message

    def send_email(self, message, *args, **kwargs):
        """Refuse every outgoing email unless the ``ebere_mail_allowed`` context key is set.

        Every SMTP send goes through here, so this also stops Odoo's own system emails. ``mail.mail._send``
        turns the exception into a failed mail (Technical > Emails).
        The key is set per mail by ``mail.mail._send`` (ALLOWED_MODELS) or by a caller that sends immediately
        (``force_send=True``); a queued mail loses the caller's context and gets blocked.
        """
        if not self.env.context.get('ebere_mail_allowed'):
            raise MailDeliveryException('Blocked by ebere_addon: email not on the allowlist')
        return super().send_email(message, *args, **kwargs)
