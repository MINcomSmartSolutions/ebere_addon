from . import controllers
from . import models
from . import services


def post_init_hook(env):
    from .services.company_service import get_or_create_company
    get_or_create_company(env)