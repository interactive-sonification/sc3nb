import time

from sc3nb import Synth
from sc3nb.osc.osc_communication import Bundler
from tests.conftest import SCBaseTest


class BundlerTest(SCBaseTest):

    __test__ = True

    def test_context_manager(self):
        time_passed = 3.0
        with Bundler(send_on_exit=False) as bundler:
            BundlerTest.sc.server.msg("/status", bundle=True)
            BundlerTest.sc.server.msg("/status", bundle=False)
            bundler.wait(time_passed)
            BundlerTest.sc.server.msg("/status", bundle=True)
        self.assertEqual(len(bundler.contents), 2)
        self.assertEqual(bundler.passed_time, time_passed)

    def test_bundler_styles(self):
        BundlerTest.sc.server.latency = 0.1
        time_between = 0.2
        with BundlerTest.sc.server.bundler(
            send_on_exit=False
        ) as server_bundler_auto_bundling:
            BundlerTest.sc.server.msg("/status", bundle=True)
            server_bundler_auto_bundling.wait(time_between)
            BundlerTest.sc.server.msg("/status", bundle=True)

        with BundlerTest.sc.server.bundler(send_on_exit=False) as server_bundler_add:
            server_bundler_add.add(0.0, "/status")
            server_bundler_add.add(time_between, "/status")

        with Bundler(timetag=self.sc.server.latency, send_on_exit=False) as bundler_add:
            bundler_add.add(0.0, "/status")
            bundler_add.add(time_between, "/status")

        server_auto_bundle = server_bundler_auto_bundling.to_raw_osc(start_time=0)
        server_bundle = server_bundler_add.to_raw_osc(start_time=0)
        bundle = bundler_add.to_raw_osc(start_time=0)

        self.assertEqual(server_bundle, bundle)
        self.assertEqual(server_auto_bundle, bundle)

    def test_bundler_messages(self):
        start = 2
        stop = 7
        dur = 0.25
        num_abs_time = 5

        t0 = time.time()
        with self.assertWarnsRegex(
            UserWarning, "SynthDesc 's.' is unknown", msg="SynthDesc seems to be known"
        ):
            with Bundler(send_on_exit=False) as bundler:
                for offset in range(1, 1 + num_abs_time):
                    with Bundler(t0 + offset):
                        Synth("s1", dict(freq=1000, dur=dur / 3))
                for n in range(start, stop):
                    dur = 0.25
                    Synth("s1", dict(freq=150 * n, dur=dur))
                    temp = Synth("s2", dict(freq=100 * n))
                    bundler.wait(dur * n / 2)
                    temp.release(dur)

        msgs = bundler.messages()
        # check if all messages are in the values
        self.assertEqual(len(msgs.values()), stop - start + 1 + num_abs_time)
        # check if all messages are in the right timetag entry
        self.assertEqual(
            list(map(len, list(msgs.values()))),
            num_abs_time * [1] + [2] + (stop - start - 1) * [3] + [1],
        )
        # check times
        expected_times = [1.0, 2.0, 3.0, 4.0, 5.0, 0.0, 0.25, 0.625, 1.125, 1.75, 2.5]
        self.assertEqual(
            [x - t0 if x > t0 else x for x in list(msgs.keys())], expected_times
        )  # need to add t0 here
        delay = 1
        msgs = bundler.messages(0, delay)
        self.assertEqual(
            [x - t0 if x > t0 else x for x in list(msgs.keys())],
            [tt + delay for tt in expected_times],
        )
        # check specific start
        msgs = bundler.messages(t0)
        self.assertEqual(
            list(msgs.keys()),
            [tt + t0 for tt in expected_times],
        )
        # check specific start + delay
        msgs = bundler.messages(t0, -t0)
        self.assertEqual(
            list(msgs.keys()),
            expected_times,
        )
