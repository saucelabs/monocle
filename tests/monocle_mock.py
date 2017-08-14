from monocle import _o, Return
from monocle.monocle_mock import MonocleMock, MagicMonocleMock

from o_test import test


@test
@_o
def test_can_yield_on_mock():
    mock = MonocleMock(return_value='mock result')
    result = yield mock()
    assert 'mock result' == result


@test
@_o
def test_nested_mock():
    mock = MonocleMock()
    mock.nested.nested.return_value = 'mock result'
    result = yield mock.nested.nested()
    assert 'mock result' == result


@test
@_o
def test_assert_called_with():
    mock = MonocleMock()
    yield mock('an arg', 'another arg')
    mock.assert_called_once_with('an arg', 'another arg')


@test
@_o
def test_str():
    def assert_str_and_repr_start_with(mock, expected):
        assert isinstance(mock.__str__(), str)
        assert isinstance(mock.__repr__(), str)
        assert mock.__str__().startswith(expected)
        assert mock.__repr__().startswith(expected)

    assert_str_and_repr_start_with(MonocleMock(),
                                   '<MonocleMock ')
    assert_str_and_repr_start_with(MagicMonocleMock(),
                                   '<MagicMonocleMock ')


@test
@_o
def test_magicmock():
    mock = MagicMonocleMock()
    mock.__len__.return_value = 3
    assert 3 == (yield mock.__len__())
