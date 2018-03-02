from __future__ import absolute_import
import sys
from . import core
from .core import _o, o, launch, Return, InvalidYieldException, log_exception

VERSION = '0.41'

_stack_name = None


def init(stack_name):
    global _stack_name
    _stack_name = stack_name
