import numpy as np

from sc3nb.sc_objects.buffer import Buffer
from tests.conftest import SCBaseTest


class BufferTest(SCBaseTest):

    __test__ = True

    def setUp(self) -> None:
        self.buffer = Buffer()

    def test_load_data(self):
        bufdata = np.random.rand(30000, 1)
        self.buffer.load_data(bufdata)
        self.assertTrue(np.allclose(self.buffer.to_array(), bufdata))
