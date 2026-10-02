from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestInlineImages(TransactionCase):

    def test_module_images_are_embedded_as_cid(self):
        body = (
            '<img src="https://odoo.example.com/ebere_addon/static/src/img/google-play-badge.png"/>'
            '<img src="/web/image/1"/>'
        )
        message = self.env['ir.mail_server'].build_email(
            'from@example.com', ['to@example.com'], 'Subject', body, subtype='html',
        )
        html = message.get_body(('html',)).get_content()
        self.assertIn('src="cid:google-play-badge.png"', html)
        self.assertIn('src="/web/image/1"', html)
        content_ids = [part['Content-ID'] for part in message.walk() if part.get_content_maintype() == 'image']
        self.assertEqual(content_ids, ['<google-play-badge.png>'])


@tagged('post_install', '-at_install')
class TestMailAllowlist(TransactionCase):

    def _send(self, context, model=False):
        mail = self.env['mail.mail'].with_context(**context).create({
            'model': model, 'email_from': 'from@example.com', 'email_to': 'to@example.com', 'subject': 'Subject', 'body_html': '<p>x</p>',
        })
        mail.send()
        return mail

    def test_unflagged_mail_is_blocked(self):
        mail = self._send({})
        self.assertEqual(mail.state, 'exception')
        self.assertIn('Blocked by ebere_addon', mail.failure_reason)

    def test_flagged_mail_is_sent(self):
        self.assertEqual(self._send({'ebere_mail_allowed': True}).state, 'sent')

    def test_invoice_mail_is_sent_without_flag(self):
        self.assertEqual(self._send({}, model='account.move').state, 'sent')
