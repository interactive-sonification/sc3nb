from unittest import TestCase

import numpy as np

from sc3nb.sclang import SCLang, SynthArgument
from tests.conftest import SCBaseTest


class SCLangTest(TestCase):
    def setUp(self) -> None:
        self.sclang = SCLang()

    def tearDown(self) -> None:
        self.sclang.kill()

    def test_started(self):
        self.sclang.start()
        self.assertTrue(self.sclang.started)


class SCLangPersistentTest(SCBaseTest):

    __test__ = True
    start_sclang = True

    def test_auto_load_synthdefs(self):
        self.assertIsNotNone(self.sc.lang.get_synth_description("s1"))
        self.assertIsNotNone(self.sc.lang.get_synth_description("s2"))

    def test_inject_pyvar(self):
        pyvar = "test"
        self.assertEqual(self.sc.lang.cmd("^pyvar.postln", get_result=True), pyvar)

    def test_convert_list_to_sc(self):
        python_list = [1, 2, 3, 4]
        self.assertIn(
            "Array",
            self.sc.lang.cmd(
                """^python_list.class""",
                get_output=True,
                pyvars={"python_list": python_list},
            ),
        )

    def test_convert_nparray_to_sc(self):
        np_array = np.array([1, 2, 3, 4])
        self.assertIn(
            "Array",
            self.sc.lang.cmd(
                """^np_array.class""", get_output=True, pyvars={"np_array": np_array}
            ),
        )

    def test_cmdg_int(self):
        a = 1234
        b = 23452
        sc_val = self.sc.lang.cmdg("""^a+^b""")
        self.assertIsInstance(sc_val, int)
        self.assertEqual(sc_val, a + b)

    def test_cmdg_float(self):
        f = 1234.5
        sc_val = self.sc.lang.cmdg("""^f.squared""")
        self.assertIsInstance(sc_val, float)
        self.assertEqual(sc_val, f ** 2)

    def test_cmdg_str(self):
        soni, fication = "soni", "fication"
        sc_val = self.sc.lang.cmdg("""^soni++^fication""")
        self.assertIsInstance(sc_val, str)
        self.assertEqual(sc_val, soni + fication)

    def test_cmdg_array(self):
        sc_val = self.sc.lang.cmdg("""Array.interpolation(11, 1.0, 2.0)""")
        self.assertIsInstance(sc_val, list)
        self.assertTrue(np.allclose(sc_val, np.linspace(1.0, 2.0, 11)))

    def test_cmdg_list(self):
        pylist = [[1]]
        sc_val = self.sc.lang.cmdg(f"""{pylist.__repr__()}""")
        self.assertIsInstance(sc_val, list)
        self.assertEqual(sc_val, pylist)

        pylist = [[[1]]]
        sc_val = self.sc.lang.cmdg(f"""{pylist.__repr__()}""")
        self.assertIsInstance(sc_val, list)
        self.assertEqual(sc_val, pylist)

        pylist = [[1], [1]]
        sc_val = self.sc.lang.cmdg(f"""{pylist.__repr__()}""")
        self.assertIsInstance(sc_val, list)
        self.assertEqual(sc_val, pylist)

        pylist = [
            [1.0, 1.0],
            [1.100000023841858, 1.100000023841858],
            [1.2000000476837158, 1.2000000476837158],
            [1.2999999523162842, 1.2999999523162842],
            [1.399999976158142, 1.399999976158142],
            [1.5, 1.5],
            [1.600000023841858, 1.600000023841858],
            [1.7000000476837158, 1.7000000476837158],
            [1.7999999523162842, 1.7999999523162842],
            [1.899999976158142, 1.899999976158142],
        ]
        sc_val = self.sc.lang.cmdg(f"""{pylist.__repr__()}""")
        self.assertIsInstance(sc_val, list)
        self.assertEqual(sc_val, pylist)

    def test_get_synth_desc(self):
        expected_synth_desc = {
            "out": SynthArgument("out", "scalar", 0.0),
            "freq": SynthArgument("freq", "control", 440.0),
            "amp": SynthArgument("amp", "control", 0.10000000149011612),
            "pan": SynthArgument("pan", "control", 0.0),
            "gate": SynthArgument("gate", "control", 1.0),
        }
        synth_desc = self.sc.lang.get_synth_description("default")
        self.assertEqual(synth_desc, expected_synth_desc)
