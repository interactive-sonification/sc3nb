import pytest

from sc3nb.helpers import ampdb, clip, cpsmidi, dbamp, linlin, midicps


def test_linlin():
    assert -50 == linlin(-1, 0, 2, 0, 100)
    assert 0 == linlin(0, 0, 2, 0, 100)
    assert 50 == linlin(1, 0, 2, 0, 100)
    assert 100 == linlin(2, 0, 2, 0, 100)
    assert 200 == linlin(4, 0, 2, 0, 100)
    assert 100 == linlin(3, 5, 105, 100, 1000, "min")


def test_clip():
    for x, y in zip([2, 3, 4, 5, 6], [3, 3, 4, 5, 5]):
        assert y == clip(x, 3, 5)


def test_midi_cps():
    for x in range(128):
        assert x == cpsmidi(midicps(x))


def test_db_amp():
    for x in range(128):
        assert x == pytest.approx(ampdb(dbamp(x)))
