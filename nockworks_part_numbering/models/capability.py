"""Identity-only capabilities cannot be supplied by an RPC JSON context."""
TOKEN = object()
KEY = '_nw_capability'


def internal(env):
    return env.context.get(KEY) is TOKEN


def context():
    return {KEY: TOKEN}
