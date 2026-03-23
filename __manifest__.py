{
    'name': "EBERE addon",
    'summary': 'This module adds additional documents for external reports and manipulates email templates',
    'author': 'MINcom Smart Solutions GmbH',
    'category': 'Base',
    'version': '17.0.1.5',
    'depends': [
        'account',
        'base',
        'l10n_de',
        'l10n_din5008',
        'mail',
        'web',
        'product',
    ],
    'data': [
        'data/products.xml',
        'views/report_templates.xml',
        'views/invoice_template.xml',
    ],
    'assets': {
        'web.report_assets_common': [
            'ebere_addon/static/src/scss/layout_custom.scss',
        ],
    },
    'installable': True,
    'auto_install': True,
    'application': False,
    'post_init_hook': 'post_init_hook',
}
