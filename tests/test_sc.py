from unittest import TestCase

from sc3nb.sc import startup
from sc3nb.sc_objects.server import ServerOptions


class SCTest(TestCase):
    def test_start_scsynth(self):
        options = ServerOptions(udp_port=57777)
        supercollider = startup(
            start_server=True,
            scsynth_options=options,
            start_sclang=False,
            with_blip=False,
        )

        self.assertIs(supercollider.server.options, options)
        self.assertIsNotNone(supercollider.server)
        with self.assertRaises(RuntimeError):
            supercollider.lang

        supercollider.exit()

    def test_start_sclang(self):
        supercollider = startup(start_server=False, start_sclang=True)

        with self.assertRaises(RuntimeError):
            supercollider.server
        self.assertIsNotNone(supercollider.lang)
        self.assertTrue(supercollider.lang.started)

        supercollider.exit()
