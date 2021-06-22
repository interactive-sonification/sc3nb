import filecmp
import tempfile
import time
from pathlib import Path

import pytest

from sc3nb.sc_objects.score import Score
from sc3nb.sc_objects.server import ServerOptions
from sc3nb.sc_objects.synthdef import SynthDef
from tests.conftest import SCBaseTest


@pytest.fixture
def files_path(tmp_path):
    return tmp_path


@pytest.mark.usefixtures("files_path")
class ScoreTest(SCBaseTest):

    __test__ = True
    start_sclang = True

    def setUp(self) -> None:
        self.assertIsNotNone(ScoreTest.sc.lang)
        synthdef = SynthDef(
            "test",
            r"""{ |out, freq = 440|
            OffsetOut.ar(out,
                SinOsc.ar(freq, 0, 0.2) * Line.kr(1, 0, 0.5, doneAction: Done.freeSelf)
            )
        }""",
        )
        with ScoreTest.sc.server.bundler(send_on_exit=False) as bundler:
            synthdef.add()
            bundler.add(0.0, "/s_new", ["test", 1003, 0, 0, "freq", 440])
            bundler.add(0.1, "/s_new", ["test", 1000, 0, 0, "freq", 440])
            bundler.add(0.1, "/s_new", ["test", 1004, 0, 0, "freq", 440])
            bundler.add(0.2, "/s_new", ["test", 1001, 0, 0, "freq", 660])
            bundler.add(0.3, "/s_new", ["test", 1002, 0, 0, "freq", 220])
            bundler.add(1, "/c_set", [0, 0])
        self.messages = bundler.messages()

    def test_record_nrt(self):
        sc3nb_osc = "test.osc"
        sc3nb_snd = "test.aif"

        sclang_osc = "sclang.osc"
        sclang_snd = "sclang.aif"

        with tempfile.TemporaryDirectory(dir=".") as tmp_path:
            tmp_path = ("." / Path(tmp_path)).resolve()
            cp = Score.record_nrt(
                self.messages,
                str(tmp_path / sc3nb_osc),
                str(tmp_path / sc3nb_snd),
                options=ServerOptions(num_output_buses=2),
            )
            print(cp)
            ScoreTest.sc.lang.cmd(
                fr"""
                var g;
                TempoClock.default.tempo = 1;
                SynthDef("test", {{ |out, freq = 440| OffsetOut.ar(out, SinOsc.ar(freq, 0, 0.2) * Line.kr(1, 0, 0.5, doneAction: Done.freeSelf))}}).store;
                g = [
                    [0.0, [\s_new, \test, 1003, 0, 0, \freq, 440]],
                    [0.1, [\s_new, \test, 1000, 0, 0, \freq, 440]],
                    [0.1, [\s_new, \test, 1004, 0, 0, \freq, 440]],
                    [0.2, [\s_new, \test, 1001, 0, 0, \freq, 660]],
                    [0.3, [\s_new, \test, 1002, 0, 0, \freq, 220]],
                    [1, [\c_set, 0, 0]] // finish
                    ];
                Score.recordNRT(
                    list: g,
                    oscFilePath: "{(tmp_path / sclang_osc).as_posix()}",
                    outputFilePath: "{(tmp_path / sclang_snd).as_posix()}"
                );
                """
            )
            t0 = time.time()
            time.sleep(0.1)
            while not (tmp_path / sclang_snd).exists():
                self.assertLess(time.time() - t0, 0.2)
