import monocle

if monocle._stack_name == 'twisted':
    from monocle.twisted_stack.eventloop import *
elif monocle._stack_name == 'tornado':
    from monocle.tornado_stack.eventloop import *
elif monocle._stack_name == 'asyncore':
    from monocle.asyncore_stack.eventloop import *
elif not monocle._stack_name:
    raise ImportError(
        "Could not import stack.\n"
        "Ensure you have called monocle.init()\n"
        "or defined MONOCLE_STACK=<stack> in the environment")
