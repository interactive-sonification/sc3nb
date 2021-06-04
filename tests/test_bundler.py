import logging
import time

from sc3nb import Synth
from sc3nb.osc.osc_communication import Bundler
from tests.conftest import SCBaseTest


class BundlerTest(SCBaseTest):

    __test__ = True

    def test_context_manager(self):
        time_passed = 3.0
        with Bundler(send_on_exit=False) as bundler:
            BundlerTest.sc.server.msg("/status", bundled=True)
            BundlerTest.sc.server.msg("/status", bundled=False)
            bundler.wait(time_passed)
            BundlerTest.sc.server.msg("/status", bundled=True)
        self.assertEqual(len(bundler.contents), 2)
        self.assertEqual(bundler.passed_time, time_passed)

    def test_bundler_styles(self):
        BundlerTest.sc.server.latency = 0.1
        time_between = 0.2
        with BundlerTest.sc.server.bundler(
            send_on_exit=False
        ) as server_bundler_auto_bundling:
            BundlerTest.sc.server.msg("/status", bundled=True)
            server_bundler_auto_bundling.wait(time_between)
            BundlerTest.sc.server.msg("/status", bundled=True)

        with BundlerTest.sc.server.bundler(send_on_exit=False) as server_bundler_add:
            server_bundler_add.add(0.0, "/status")
            server_bundler_add.add(time_between, "/status")

        with Bundler(
            timestamp=self.sc.server.latency, send_on_exit=False
        ) as bundler_add:
            bundler_add.add(0.0, "/status")
            bundler_add.add(time_between, "/status")

        server_auto_bundle = server_bundler_auto_bundling.build(time_offset=0).dgram
        server_bundle = server_bundler_add.build(time_offset=0).dgram
        bundle = bundler_add.build(time_offset=0).dgram

        self.assertEqual(server_bundle, bundle)
        self.assertEqual(server_auto_bundle, bundle)

    def test_bundler_message_skip(self):
        value = 1337
        with Bundler() as bundler:
            bundler.add(0, "/sync", value)
        t0 = time.time()
        while self.sc.server.msg_queues["/synced"].size <= 0:
            self.assertLess(time.time() - t0, 0.2)
        with self.assertLogs(level=logging.WARNING) as log:
            sync_val = BundlerTest.sc.server.sync()
        self.assertTrue("skipped value 1337" in log.output[-1])
        self.assertTrue(sync_val)

    def test_bundler_messages(self):
        start = 2
        stop = 7
        with self.assertWarnsRegex(
            UserWarning, "SynthDesc 's.' is unknown", msg="SynthDesc seems to be known"
        ):
            with Bundler(send_on_exit=False) as bundler:
                for n in range(start, stop):
                    dur = 0.25
                    Synth("s1", dict(freq=150 * n, dur=dur))
                    temp = Synth("s2", dict(freq=100 * n))
                    bundler.wait(dur * n)
                    temp.release(dur)
                    print(n)

        msgs = bundler.messages()
        self.assertEqual(len(msgs), stop - start + 1)
        self.assertEqual(
            list(map(len, list(msgs.values()))), [2] + (stop - start - 1) * [3] + [1]
        )
