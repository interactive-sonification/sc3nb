import time
import warnings

from sc3nb.sc_objects.node import AddAction, Group, GroupInfo, Synth
from tests.conftest import SCBaseTest


class GroupTest(SCBaseTest):

    __test__ = True

    def setUp(self) -> None:
        with self.assertRaises(RuntimeError):
            GroupTest.sc.lang
        warnings.simplefilter("always", UserWarning)
        self.custom_nodeid = 1010
        self.group = Group(nodeid=self.custom_nodeid)
        GroupTest.sc.server.sync()

    def tearDown(self) -> None:
        nodeid = self.group.nodeid
        self.assertIn(nodeid, self.sc.server.nodes)
        self.group.free()
        self.group.wait(timeout=1)
        del self.group  # make sure that group is deleted from registry
        t0 = time.time()
        while nodeid in self.sc.server.nodes:
            time.sleep(0.005)
            if time.time() - t0 > 0.2:
                self.fail("NodeID is still in server.nodes")
        self.assertNotIn(nodeid, self.sc.server.nodes)
        with self.assertRaises(KeyError):
            del self.sc.server.nodes[nodeid]

    def test_node_registry(self):
        copy1 = Group(nodeid=self.group.nodeid, new=False)
        copy2 = Group(nodeid=self.custom_nodeid, new=False)
        self.assertIs(self.group, copy1)
        self.assertIs(self.group, copy2)
        self.assertIs(copy1, copy2)
        del copy1, copy2

    def test_setattr(self):
        with self.assertWarnsRegex(
            UserWarning, "SynthDesc 's2' is unknown", msg="SynthDesc seems to be known"
        ):
            synth1 = Synth("s2", controls={"amp": 0.0}, target=self.group)
        with self.assertWarnsRegex(
            UserWarning, "SynthDesc 's2' is unknown", msg="SynthDesc seems to be known"
        ):
            synth2 = Synth("s2", controls={"amp": 0.0}, target=self.group)
        GroupTest.sc.server.sync()
        cmd_args = {"pan": -1.0, "num": 1}
        for name, value in cmd_args.items():
            self.group.set(name, value)
        GroupTest.sc.server.sync()
        self.assertEqual(synth1.group, self.group.nodeid)
        self.assertEqual(synth2.group, self.group.nodeid)
        for name, value in cmd_args.items():
            self.assertAlmostEqual(synth1.get(name), value)
            self.assertAlmostEqual(synth2.get(name), value)

    # TODO does only trigger a warning if the new group is not the old/same group
    # This seems like a SuperCollider Problem
    def test_new_warning(self):
        with self.assertLogs(level="WARNING") as log:
            self.group.new(target=0)
            time.sleep(0.1)
        self.assertTrue("duplicate node ID" in log.output[-1])

    def test_query(self):
        query_result = self.group.query()
        self.assertIsInstance(query_result, GroupInfo)
        self.assertEqual(query_result.nodeid, self.custom_nodeid)
        self.assertEqual(query_result.group, GroupTest.sc.server.default_group.nodeid)
        self.assertEqual(query_result.prev_nodeid, -1)
        self.assertEqual(query_result.next_nodeid, -1)
        self.assertEqual(query_result.tail, -1)
        self.assertEqual(query_result.head, -1)
