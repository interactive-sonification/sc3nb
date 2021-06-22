import logging
import time

from sc3nb import Synth
from sc3nb.osc.osc_communication import Bundler, convert_to_sc3nb_osc
from tests.conftest import SCBaseTest


class OSCTest(SCBaseTest):

    __test__ = True

    def test_bundler_message_skip(self):
        value = 1337
        with Bundler() as bundler:
            bundler.add(0, "/sync", value)
        t0 = time.time()
        while self.sc.server.msg_queues["/synced"].size <= 0:
            self.assertLess(time.time() - t0, 0.2)
        with self.assertLogs(level=logging.WARNING) as log:
            sync_val = OSCTest.sc.server.sync()
        self.assertTrue("skipped value 1337" in log.output[-1])
        self.assertTrue(sync_val)

    def test_osc_conversion(self):
        with self.assertWarnsRegex(
            UserWarning, "SynthDesc 's.' is unknown", msg="SynthDesc seems to be known"
        ):
            with Bundler(send_on_exit=False) as bundler:
                for num in range(6):
                    for i in range(num):
                        Synth("s1", dict(freq=1000 * num + i, dur=1 / 3))
                    bundler.wait(1)
        t0 = time.time() + 5
        original = list(bundler.messages(t0).items())
        converted = list(
            convert_to_sc3nb_osc(bundler.to_pythonosc(t0)).messages().items()
        )
        assert len(original) == len(converted)
        for i in range(len(original)):
            self.assertAlmostEqual(original[i][0], converted[i][0], places=6)
            assert len(original[i][1]) == len(converted[i][1])
            for j in range(len(original[i][1])):
                assert original[i][1][j].address == converted[i][1][j].address
                assert original[i][1][j].parameters == converted[i][1][j].parameters
