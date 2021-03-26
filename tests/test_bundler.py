from sc3nb.osc.osc_communication import Bundler
from tests.test_sc import SCBaseTest

class BundlerTest(SCBaseTest):

    __test__ = True

    def setUp(self) -> None:
        self.bundler = Bundler()

    def test_context_manager(self):
        time_passed = 3.0
        with self.bundler:
            BundlerTest.sc.server.msg("/status", bundled=True)
            BundlerTest.sc.server.msg("/status", bundled=False)
            self.bundler.wait(time_passed)
            BundlerTest.sc.server.msg("/status", bundled=True)
        self.assertEqual(len(self.bundler.contents), 2)
        self.assertEqual(self.bundler.passed_time, time_passed)
