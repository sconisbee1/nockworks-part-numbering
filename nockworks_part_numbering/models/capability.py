from odoo.exceptions import AccessError

TOKEN = object()
KEY = '_nw_capability'


def internal(env):
    return env.context.get(KEY) is TOKEN


def context():
    return {KEY: TOKEN}


def require_internal(env):
    if not internal(env):
        raise AccessError(env._('This private numbering operation requires the internal allocation service.'))
