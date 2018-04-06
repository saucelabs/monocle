from __future__ import absolute_import
import os
from . import core
from .core import _o, o, launch, Return, InvalidYieldException, log_exception

VERSION = '0.42'

_stack_name = os.getenv('MONOCLE_STACK')


def init(stack_name):
    global _stack_name
    _stack_name = stack_name
