from unittest import TestCase
from sc3nb.sc import startup
from sc3nb.sc_objects.server import ServerOptions

class SCBaseTest(TestCase):

    __test__ = False
    sc = None
    start_sclang = False

    @classmethod
    def setUpClass(cls) -> None:
        cls.sc = startup(start_server=True,
                         scsynth_options=ServerOptions(udp_port=57777),
                         with_blip=False,
                         start_sclang=cls.start_sclang)
        cls.sc.server.dump_osc(1)
        cls.sc.server.sync()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.sc.exit()

class SCTest(TestCase):

    def test_start_synth(self):
        options = ServerOptions()
        supercollider = startup(start_server=True, scsynth_options=options, start_sclang=False)

        self.assertIs(supercollider.server.options, options)
        self.assertIsNotNone(supercollider.server)
        with self.assertRaises(RuntimeWarning):
            supercollider.lang

        supercollider.exit()

    def test_start_sclang(self):
        supercollider = startup(start_server=False, start_sclang=True)

        with self.assertRaises(RuntimeWarning):
            supercollider.server
        self.assertIsNotNone(supercollider.lang)

        supercollider.exit()
