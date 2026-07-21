"""Shared module-level ctx reference for dispatch_tool in slash-commands.

Avoids circular imports between __init__.py and handlers/__init__.py.
"""
_CTX = None


def set_ctx(ctx):
    global _CTX
    _CTX = ctx


def get_ctx():
    return _CTX
