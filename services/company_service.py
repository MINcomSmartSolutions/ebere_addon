import base64
import os
import logging
import urllib.request

_logger = logging.getLogger(__name__)

# TODO: Needs one more check before executing env dependant functions, for urls and other potentially vulnurable envs.

# Environment variable → res.company field mapping
_ENV_FIELD_MAP = {
    'COMPANY_ADRESS': 'street',
    'COMPANY_PLZ': 'zip',
    'COMPANY_CITY': 'city',
    'COMPANY_CONTACT_EMAIL': 'email',
    'COMPANY_PHONE': 'phone',
    'COMPANY_WEBSITE': 'website',
}


def _normalize_hex_color(value):
    """Return a hex color string that always starts with '#'.

    Accepts both ``FF5733`` and ``#FF5733``.
    """
    value = value.strip()
    if not value.startswith('#'):
        value = f'#{value}'
    return value


def _fetch_logo(url):
    """Download *url* and return its content as a base64-encoded bytes string.

    Returns ``None`` and logs a warning on any error.
    """
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:  # noqa: S310
            return base64.b64encode(resp.read()).decode('ascii')
    except Exception as exc:
        _logger.warning('Could not fetch company logo from %r: %s', url, exc)
        return None


def _read_company_vals():
    """Build a dict of res.company field values from environment variables.

    Returns ``None`` when ``COMPANY_NAME`` is not set.
    """
    name = os.environ.get('COMPANY_NAME', '').strip()
    if not name:
        return None

    vals = {'name': name}

    for env_key, field in _ENV_FIELD_MAP.items():
        value = os.environ.get(env_key, '').strip()
        if value:
            vals[field] = value

    # primary_color expects a '#RRGGBB' hex string
    color = os.environ.get('COMPANY_PRIMARY_COLOR', '').strip()
    if color:
        vals['primary_color'] = _normalize_hex_color(color)

    # Combine HR register court and number into company_registry
    hr_number = os.environ.get('COMPANY_HR_NUMBER', '').strip()
    hr_register = os.environ.get('COMPANY_HR_REGISTER', '').strip()
    if hr_register and hr_number:
        vals['company_registry'] = f"{hr_register}, {hr_number}"
    elif hr_number:
        vals['company_registry'] = hr_number

    # Logo: fetch from URL and store as base64 binary
    logo_url = os.environ.get('COMPANY_LOGO_URL', '').strip()
    if logo_url:
        logo_data = _fetch_logo(logo_url)
        if logo_data:
            vals['logo'] = logo_data

    return vals


def _resolve_static_vals(env):
    """Resolve static (non-dynamic) company fields: EUR currency, Germany country.

    Language (de_DE) is returned separately as it must be set on the
    company's partner_id, not on res.company itself.
    """
    vals = {}

    currency = env['res.currency'].sudo().search([('name', '=', 'EUR')], limit=1)
    if currency:
        vals['currency_id'] = currency.id
    else:
        _logger.warning('EUR currency not found – skipping currency assignment')

    country = env['res.country'].sudo().search([('code', '=', 'DE')], limit=1)
    if country:
        vals['country_id'] = country.id
    else:
        _logger.warning('Country DE not found – skipping country assignment')

    return vals


def _ensure_lang_de(env):
    """Activate de_DE if needed and return its code, or None if unavailable."""
    lang = env['res.lang'].sudo().search([('code', '=', 'de_DE')], limit=1)
    if not lang:
        lang = env['res.lang'].sudo().with_context(active_test=False).search(
            [('code', '=', 'de_DE')], limit=1
        )
        if lang:
            lang.write({'active': True})
    if lang:
        return lang.code
    _logger.warning('Language de_DE not found – skipping language assignment')
    return None


def get_or_create_company(env):
    """Return the ``res.company`` record for the configured ``COMPANY_NAME``.

    Lookup order:
    1. Company already exists by name → return it as-is.
    2. Company does not exist → update the Odoo default company (base.main_company)
       with the provided details instead of creating a new one from scratch.
       Creating a company via ORM skips journal/account initialisation, so the
       default company (which already has all journals) is always used as the base.
       Otherwise, throws accounting errors since newly created company would have no journals.

    Returns ``None`` when ``COMPANY_NAME`` is not configured.
    """
    vals = _read_company_vals()
    if not vals:
        _logger.warning('COMPANY_NAME env var not set – skipping company setup')
        return None

    static_vals = _resolve_static_vals(env)
    lang_code = _ensure_lang_de(env)

    Company = env['res.company'].sudo()
    company = Company.search([('name', '=', vals['name'])], limit=1)

    if company:
        _logger.debug('Using existing company %r (id=%s)', company.name, company.id)
        return company

    # Fall back to the Odoo default company so that all journals/accounts are
    # already in place. We simply rename and reconfigure it
    try:
        company = env.ref('base.main_company').sudo()
    except Exception:
        company = Company.search([], limit=1, order='id asc')

    if not company:
        _logger.error('No existing company found to configure – giving up')
        return None

    update_vals = {**vals, **static_vals}
    company.write(update_vals)
    if lang_code and company.partner_id:
        company.partner_id.sudo().write({'lang': lang_code})
    _logger.info('Reconfigured default company → %r (id=%s)', company.name, company.id)
    return company
