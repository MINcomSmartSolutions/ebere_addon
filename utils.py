import logging

_logger = logging.getLogger(__name__)


def ebere_init_parameters(env):
    """
    Shared initialization logic for config parameters and system setup.
    Can be called from both init hooks and controllers to ensure consistent configuration.

    This function works in all contexts (init hooks and controllers) by calling sudo()
    on individual model instances rather than on the environment itself, which avoids
    the "Expected singleton: res.users()" error.

    PS. Parameter changes are prohibited and controlled via ir.config_parameter.py

    Args:
        env: Odoo environment object
    """
    # Note: We don't call env.sudo() here because:
    # 1. In controller contexts, env doesn't have sudo() method
    # 2. We call sudo() on each model instance instead, which works everywhere

    # Set default language and timezone context
    env.context = dict(env.context, lang='de_DE')
    env.context = dict(env.context, tz='Europe/Berlin')

    # Disable default digest emails
    try:
        env['ir.config_parameter'].sudo().set_param('digest.default_digest_emails', 'False')
        _logger.info("Disabled digest.default_digest_emails")
    except Exception as e:
        _logger.warning("Failed to disable digest.default_digest_emails: %s", e)

    # Disable password reset email
    try:
        env['ir.config_parameter'].sudo().set_param('auth_signup.reset_password', 'False')
        _logger.info("Disabled auth_signup.reset_password")
    except Exception as e:
        _logger.warning("Failed to disable auth_signup.reset_password %s", e)

    # Disable sale.async_emails
    try:
        env['ir.config_parameter'].sudo().set_param('sale.async_emails', 'False')
        _logger.info("Disabled sale.async_emails")
    except Exception as e:
        _logger.warning("Failed to disable sale.async_emails %s", e)

    # Disable default digest ID
    try:
        env['ir.config_parameter'].sudo().set_param('digest.default_digest_id', '0')
        _logger.info("Disabled digest.default_digest_id")
    except Exception as e:
        _logger.warning("Failed to disable digest.default_digest_id: %s", e)

    # Deactivate any existing digests
    try:
        digests = env['digest.digest'].sudo().search([])
        if digests:
            digests.write({'state': 'deactivated'})
            _logger.info(f"Deactivated {len(digests)} digest records")
    except Exception as e:
        _logger.warning("Failed to deactivate digest.digest records: %s", e)

    # Note: Mail servers remain active for controlled/manual email sending
    # Automatic emails are disabled via config parameters below

    # Disable sale order confirmation emails
    try:
        env['ir.config_parameter'].sudo().set_param('sale.auto_send_order_confirmation', 'False')
        _logger.info("Disabled automatic sale order confirmation emails")
    except Exception as e:
        _logger.warning("Failed to disable sale order confirmation emails: %s", e)

    try:
        env['ir.config_parameter'].sudo().set_param('sale.async_emails', 'False')
        _logger.info("Disabled automatic sale.async_emails")
    except Exception as e:
        _logger.warning("Failed to disable sale.async_emails %s", e)

    # Deactivate scheduled email actions (mass mailings, etc.)
    try:
        scheduled_actions = env['ir.cron'].sudo().search([
            '|', ('name', 'ilike', 'digest'),
            ('model_id.model', 'in', ['mail.mail', 'mail.message', 'digest.digest'])
        ])
        if scheduled_actions:
            scheduled_actions.write({'active': False})
            _logger.info(f"Deactivated {len(scheduled_actions)} email-related scheduled actions")
    except Exception as e:
        _logger.warning("Failed to deactivate scheduled email actions: %s", e)

    # Set report.url to http://localhost:8069
    try:
        env['ir.config_parameter'].sudo().set_param('report.url', 'http://localhost:8069')
        _logger.info("Set report.url to http://localhost:8069")
    except Exception as e:
        _logger.warning("Failed to set report.url: %s", e)

    # Check if de_DE language is enabled
    try:
        lang = env['res.lang'].sudo().search([('code', '=', 'de_DE')], limit=1)
        if not lang:
            _logger.warning("German language (de_DE) not found, please install it")
        elif not lang.active:
            lang.write({'active': True})
            _logger.info("German language (de_DE) activated")
        else:
            _logger.info("German language (de_DE) is already active")
    except Exception as e:
        _logger.warning("Failed to check/activate de_DE language: %s", e)

    # Check current company and its fiscal country
    try:
        # Try to get company from env.company, fallback to search
        company = None
        if hasattr(env, 'company'):
            company = env.company
        if not company:
            company = env['res.company'].sudo().search([], limit=1)

        if company:
            _logger.info(f"Using company: {company.name} (id: {company.id})")
            if company.country_id and company.country_id.code != 'DE':
                _logger.warning(
                    f"Company {company.name} does not have Germany set as fiscal country. "
                    f"Current: {company.country_id.name or 'Not set'}"
                )
            elif company.country_id:
                _logger.info(f"Company {company.name} has correct fiscal country: {company.country_id.name}")
            else:
                _logger.warning(f"Company {company.name} has no fiscal country set")
        else:
            _logger.warning("No company found in environment")
    except Exception as e:
        _logger.warning("Failed to check company fiscal country: %s", e)

