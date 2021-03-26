import time
import warnings

from tests.test_sc import SCBaseTest
from sc3nb.sc_objects.node import Synth, SynthInfo


class SynthTest(SCBaseTest):

    __test__ = True

    def setUp(self) -> None:
        with self.assertRaises(RuntimeWarning):
            SynthTest.sc.lang
        self.custom_nodeid = 42
        self.args = {"amp": 0.0, "num": 3}
        warnings.simplefilter("always", UserWarning)
        with self.assertWarnsRegex(
            UserWarning, "SynthDesc is unknown", msg="SynthDesc seems to be known"
        ):
            self.synth = Synth("s2", args=self.args, nodeid=self.custom_nodeid)
        self.assertIsNone(self.synth._synth_desc)

    def tearDown(self) -> None:
        self.synth.free()

    def test_node_registry(self):
        self.assertIs(self.synth, Synth(nodeid=self.synth.nodeid, new=False))

    def test_too_many_arguments(self):
        with self.assertRaises(TypeError):
            Synth("s2", self.args, "this is too much!")

    def test_getattr(self):
        for name, value in self.args.items():
            self.assertAlmostEqual(self.synth.__getattr__(name), value)
        with self.assertRaises(AttributeError):
            self.synth.freq

    def test_setattr(self):
        for name, value in {"amp": 0.3, "num": 1}.items():
            self.synth.__setattr__(name, value)
            self.assertAlmostEqual(self.synth.__getattr__(name), value)
        # with self.assertWarnsRegex(UserWarning, "Setting 'freq' as python attribute"):
        self.synth.freq = 420

    def test_set_get(self):
        with self.assertWarnsRegex(UserWarning, "Setting 'freq' as python attribute"):
            self.synth.freq = 420  # should warn if setting attribute
        self.assertAlmostEqual(
            self.synth.get("freq"), 400
        )  # default freq of s2 SynthDef
        with self.assertWarnsRegex(UserWarning, "recognized as Node Parameter now"):
            self.synth.set("freq", 100)
        self.assertAlmostEqual(self.synth.get("freq"), 100)
        self.synth.freq = 300
        self.assertAlmostEqual(self.synth.get("freq"), 300)

    def test_new_warning(self):
        with self.assertWarnsRegex(UserWarning, "duplicate node ID"):
            self.synth.new()
            time.sleep(0.1)

    def test_query(self):
        query_result = self.synth.query()
        self.assertIsInstance(query_result, SynthInfo)
        self.assertEqual(query_result.nodeid, self.custom_nodeid)
        self.assertEqual(query_result.group, SynthTest.sc.server.default_group.nodeid)
        self.assertEqual(query_result.prev_nodeid, -1)
        self.assertEqual(query_result.next_nodeid, -1)
