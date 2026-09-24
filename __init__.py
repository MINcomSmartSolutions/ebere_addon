import logging
from . import controllers
from . import models
from . import services

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    from .services.company_service import get_or_create_company
    get_or_create_company(env)

    from .utils import ebere_init_parameters
    _logger.info("Running Ebere module initialization hook")
    ebere_init_parameters(env)
    _logger.info("Ebere module initialization hook completed")
