import time

from sc3nb.sc_objects.node import Synth
from tests.conftest import SCBaseTest


class SynthTestWithSClang(SCBaseTest):

    __test__ = True
    start_sclang = True

    def setUp(self) -> None:
        self.assertIsNotNone(SynthTestWithSClang.sc.lang)
        self.custom_nodeid = 42
        self.all_synth_args = {"freq": 400, "amp": 0.3, "num": 4, "pan": 0, "lg": 0.1}
        self.synth = Synth("s2", nodeid=self.custom_nodeid)

    def tearDown(self) -> None:
        self.synth.free()
        time.sleep(0.1)

    def test_synth_desc(self):
        self.assertIsNotNone(self.synth.synth_desc)
        for name, synth_arg in self.synth.synth_desc.items():
            self.assertEqual(name, synth_arg.name)
            self.assertAlmostEqual(self.synth.get(name), synth_arg.default)

    def test_getattr(self):
        for name, value in self.all_synth_args.items():
            self.assertAlmostEqual(self.synth.__getattr__(name), value)
