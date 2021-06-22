import time
from queue import Empty

import pytest

from sc3nb.sc_objects.node import Group, Synth
from tests.conftest import SCBaseTest


class NodeTest(SCBaseTest):

    __test__ = True

    def setUp(self) -> None:
        with self.assertRaises(RuntimeError):
            NodeTest.sc.lang

    def test_wait(self):
        duration = 0.15
        tol = 0.05

        def check(synth):
            self.assertEqual(synth.is_playing, None)
            self.assertEqual(synth.started, True)
            self.assertEqual(synth.freed, False)
            self.assertEqual(synth.group, self.sc.server.default_group.nodeid)
            t_wait_for_notification = time.time()
            while not synth.is_playing:
                if time.time() - t_wait_for_notification > 0.15:
                    self.fail("Waiting for /n_go notification took too long.")
            self.assertEqual(synth.is_playing, True)
            self.assertEqual(synth.started, True)
            self.assertEqual(synth.freed, False)
            synth.wait(timeout=1)
            time_played = time.time() - t0
            self.assertEqual(synth.is_playing, False)
            self.assertEqual(synth.started, False)
            self.assertEqual(synth.freed, True)
            self.assertEqual(synth.group, None)
            self.assertLessEqual(time_played, duration + tol)
            self.assertGreaterEqual(time_played, duration - tol)

        t0 = time.time()
        with self.assertWarnsRegex(
            UserWarning, "SynthDesc 's1' is unknown", msg="SynthDesc seems to be known"
        ):
            s1_synth = Synth("s1", controls={"dur": duration, "amp": 0.0})
        check(s1_synth)
        t0 = time.time()
        s1_synth.new()
        check(s1_synth)

    def test_fast_wait(self):
        duration = 0.15
        tol = 0.05

        def check(synth):
            self.assertEqual(synth.is_playing, False)
            self.assertEqual(synth.started, False)
            self.assertEqual(synth.freed, True)
            time_played = time.time() - t0
            self.assertLessEqual(time_played, duration + tol)
            self.assertGreaterEqual(time_played, duration - tol)

        t0 = time.time()
        with self.assertWarnsRegex(
            UserWarning, "SynthDesc 's1' is unknown", msg="SynthDesc seems to be known"
        ):
            s1_synth = Synth("s1", controls={"dur": duration, "amp": 0.0})
        s1_synth.wait(timeout=1)
        check(s1_synth)

        t0 = time.time()
        s1_synth.new()
        s1_synth.wait(timeout=1)
        check(s1_synth)

    def test_too_many_arguments(self):
        with self.assertRaises(TypeError):
            Synth("s2", {"amp": 0.0}, "this is too much!")
        with self.assertRaises(TypeError):
            Group(101, "this is too much!")

    def test_reuse_nodeid(self):
        with self.assertWarnsRegex(
            UserWarning, "SynthDesc 's2' is unknown", msg="SynthDesc seems to be known"
        ):
            synth1 = Synth("s2", {"amp": 0.0})
            nodeid = synth1.nodeid
            synth1.free()
            synth1.wait(timeout=1)
            group = Group(nodeid=nodeid)
            with self.assertRaisesRegex(RuntimeError, "Tried to get "):
                Synth("s2", nodeid=nodeid)
            group.free()
            group.wait(timeout=1)
            synth2 = Synth("s2", nodeid=nodeid)
            synth2.free()
            synth2.wait(timeout=1)

    @pytest.mark.allowloggingwarn
    def test_duplicate(self):
        self.assertNotIn("/s_new", self.sc.server.fails)
        with self.assertWarnsRegex(
            UserWarning, "SynthDesc 's2' is unknown", msg="SynthDesc seems to be known"
        ):
            synth1 = Synth("s2", controls={"amp": 0.0})
            wait_t0 = time.time()
            synth1.new(controls={"amp": 0.0})
            while not "/s_new" in self.sc.server.fails:
                self.assertLessEqual(time.time() - wait_t0, 0.5)
            self.assertEqual(self.sc.server.fails["/s_new"].get(), "duplicate node ID")
            synth1.free()
            synth1.wait(timeout=1)
            synth1.new({"amp": 0.0})
            synth1.free()
            synth1.wait(timeout=1)
            with self.assertRaises(Empty):
                self.sc.server.fails["/s_new"].get(timeout=0.5)
