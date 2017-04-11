import sys
import core
from core import _o, o, launch, Return, InvalidYieldException, log_exception

VERSION = '0.39'

_stack_name = None


def init(stack_name):
    global _stack_name
    _stack_name = stack_name
