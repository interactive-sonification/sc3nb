import time
import warnings

from sc3nb.sc_objects.node import AddAction, Group, GroupInfo, Synth
from tests.test_sc import SCBaseTest


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
        self.group.free()

    def test_node_registry(self):
        self.assertIs(self.group, Group(nodeid=self.group.nodeid, new=False))
        self.assertIs(self.group, Group(nodeid=self.custom_nodeid, new=False))

    def test_too_many_arguments(self):
        with self.assertRaises(TypeError):
            Group(101, "this is too much!")

    def test_setattr(self):
        with self.assertWarnsRegex(
            UserWarning, "SynthDesc is unknown", msg="SynthDesc seems to be known"
        ):
            synth1 = Synth("s2", target=self.group)
            synth2 = Synth("s2", target=self.group)
        GroupTest.sc.server.sync()
        args = {"amp": 0.3, "num": 1}
        for name, value in args.items():
            self.group.set(name, value)
        GroupTest.sc.server.sync()
        for name, value in args.items():
            self.assertAlmostEqual(synth1.get(name), value)
            self.assertAlmostEqual(synth2.get(name), value)

    # TODO does only trigger a warning if the new group is not the old/same group
    # This seems like a SuperCollider Problem
    def test_new_warning(self):
        with self.assertWarnsRegex(UserWarning, "duplicate node ID"):
            self.group.new(target=0)
            time.sleep(0.2)

    def test_query(self):
        query_result = self.group.query()
        self.assertIsInstance(query_result, GroupInfo)
        self.assertEqual(query_result.nodeid, self.custom_nodeid)
        self.assertEqual(query_result.group, GroupTest.sc.server.default_group.nodeid)
        self.assertEqual(query_result.prev_nodeid, -1)
        self.assertEqual(query_result.next_nodeid, -1)
        self.assertEqual(query_result.tail, -1)
        self.assertEqual(query_result.head, -1)
