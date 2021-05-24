import logging
from unittest import TestCase

import pytest

from sc3nb.sc import startup
from sc3nb.sc_objects.server import ServerOptions


@pytest.fixture(autouse=True)
def no_logs_gte_error(caplog, request):
    yield  # Yielding here runs the test itself
    if "allowloggingwarn" in request.keywords:
        return
    errors = [
        record
        for record in caplog.get_records("call")
        if record.levelno >= logging.WARNING
    ]
    formatter = logging.Formatter("%(name)s:%(lineno)d  %(levelname)s - %(message)s")
    assert (
        not errors
    ), f"Got Warning logged: {[formatter.format(error) for error in errors]}"


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "allowloggingwarn: mark for allowing logger warnings"
    )


class SCBaseTest(TestCase):

    __test__ = False
    sc = None
    start_sclang = False

    @classmethod
    def setUpClass(cls) -> None:
        cls.sc = startup(
            start_server=True,
            scsynth_options=ServerOptions(udp_port=57777, max_logins=3),
            with_blip=False,
            start_sclang=cls.start_sclang,
        )
        cls.sc.server.dump_osc(1)
        cls.sc.server.sync()
        if cls.start_sclang:
            cls.sc.server.mute()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.sc.exit()