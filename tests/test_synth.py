import time
import warnings

from sc3nb.sc_objects.node import Synth, SynthInfo
from tests.conftest import SCBaseTest


class SynthTest(SCBaseTest):

    __test__ = True

    def setUp(self) -> None:
        with self.assertRaises(RuntimeError):
            SynthTest.sc.lang
        self.custom_nodeid = 42
        self.synth_args = {"amp": 0.0, "num": 3}
        warnings.simplefilter("always", UserWarning)
        with self.assertWarnsRegex(
            UserWarning, "SynthDesc 's2' is unknown", msg="SynthDesc seems to be known"
        ):
            self.synth = Synth(
                "s2", controls=self.synth_args, nodeid=self.custom_nodeid
            )
        self.assertIsNone(self.synth._synth_desc)
        self.sc.server.sync()

    def tearDown(self) -> None:
        nodeid = self.synth.nodeid
        self.assertIn(nodeid, self.sc.server.nodes)
        self.synth.free()
        self.synth.wait()
        del self.synth  # make sure that synth is deleted from registry
        t0 = time.time()
        while nodeid in self.sc.server.nodes:
            time.sleep(0.005)
            if time.time() - t0 > 0.2:
                self.fail("NodeID is still in server.nodes")
        self.assertNotIn(nodeid, self.sc.server.nodes)
        with self.assertRaises(KeyError):
            del self.sc.server.nodes[nodeid]

    def test_node_registry(self):
        copy1 = Synth(nodeid=self.synth.nodeid, new=False)
        copy2 = Synth(nodeid=self.custom_nodeid, new=False)
        self.assertIs(self.synth, copy1)
        self.assertIs(self.synth, copy2)
        self.assertIs(copy1, copy2)
        del copy1, copy2

    def test_set_get(self):
        for name, value in {"amp": 0.0, "num": 1}.items():
            self.synth.__setattr__(name, value)
            self.assertAlmostEqual(self.synth.__getattr__(name), value)

        with self.assertWarnsRegex(UserWarning, "Setting 'freq' as python attribute"):
            with self.assertRaisesRegex(AttributeError, "no attribute 'freq'"):
                self.synth.__getattribute__(
                    "freq"
                )  # should not have a python attribute named freq
            self.synth.freq = 420  # should warn if setting attribute

        self.assertAlmostEqual(
            self.synth.get("freq"), 400
        )  # default freq of s2 SynthDef

        with self.assertWarnsRegex(UserWarning, "recognized as Node Parameter now"):
            self.synth.set("freq", 100)
        self.assertAlmostEqual(self.synth.get("freq"), 100)

        self.synth.freq = 300
        self.assertAlmostEqual(self.synth.get("freq"), 300)

        for name, value in self.synth_args.items():
            self.assertAlmostEqual(self.synth.__getattr__(name), value)

    def test_new_warning(self):
        with self.assertLogs(level="WARNING") as log:
            self.synth.new()
            time.sleep(0.1)
        self.assertTrue("duplicate node ID" in log.output[-1])

    def test_query(self):
        query_result = self.synth.query()
        self.assertIsInstance(query_result, SynthInfo)
        self.assertEqual(query_result.nodeid, self.custom_nodeid)
        self.assertEqual(query_result.group, SynthTest.sc.server.default_group.nodeid)
        self.assertEqual(query_result.prev_nodeid, -1)
        self.assertEqual(query_result.next_nodeid, -1)
