try:
    from mock import CallableMixin, Mock, MagicMock
except ImportError:
    raise ImportError('monocle_mock requires mock as an additional dependency')

from monocle.callback import Callback


class _MonocleCallableMixin(CallableMixin):
    def _mock_call(self, *args, **kwargs):
        ''' Mock seems to run all returns through this method, so we intercept
        the return value and wrap it in monocle magic. '''
        result = super(_MonocleCallableMixin, self)._mock_call(*args, **kwargs)
        # Special case for when a person tries to print a MonocleMock directly.
        # In this case the result is a string, and the content is something
        # like <MonocleMock id='4470907728'>. So we look for that particular
        # string and do NOT wrap it in a Monocle callback.
        if (isinstance(result, str) and 
            (result.startswith('<MonocleMock ') or
             result.startswith('<MagicMonocleMock '))):
            return result

        cb = Callback()
        cb(result)
        return cb


class MonocleMock(_MonocleCallableMixin, Mock):
    ''' Use this in the same way you would a regular Python Mock, but for
    monocle'd methods. For example:

    THE OLD WAY:
    @test
    @_o
    def test_something_with_a_yield():
        my_mock = Mock()
        my_mock.chickens.return_value = "cluck"
        result = yield my_mock.chickens()        # <----- THIS FAILS!
        assert "cluck" == result

    THE NEW WAY:
    @test
    @_o
    def test_something_with_a_yield():
        my_mock = MonocleMock()                  # note difference in name
        my_mock.chickens.return_value = "cluck"
        result = yield my_mock.chickens()        # <----- THIS WORKS!
        assert "cluck" == result
    '''
    pass


class MagicMonocleMock(_MonocleCallableMixin, MagicMock):
    ''' Same as above, but also handles "magic" methods (such as __gte__,
    __lte__, etc...)
    '''
    pass
