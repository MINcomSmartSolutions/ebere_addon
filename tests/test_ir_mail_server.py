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
