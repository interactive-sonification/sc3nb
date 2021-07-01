import aifc
import tempfile
import time
from pathlib import Path

from sc3nb.osc.osc_communication import OSCMessage
from sc3nb.sc_objects.score import Score
from sc3nb.sc_objects.server import ServerOptions
from sc3nb.sc_objects.synthdef import SynthDef
from tests.conftest import SCBaseTest


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

    def test_score(self):
        sc3nb_osc = "test.osc"
        sc3nb_snd = "test.aiff"

        sclang_osc = "sclang.osc"
        sclang_snd = "sclang.aiff"

        with tempfile.TemporaryDirectory(dir=".") as tmp_path:
            tmp_path = ("." / Path(tmp_path)).resolve()
            cp = Score.record_nrt(
                self.messages,
                str(tmp_path / sc3nb_osc),
                str(tmp_path / sc3nb_snd),
                options=ServerOptions(num_output_buses=2),
                header_format="AIFF",
            )
            print(cp)
            (_, port), _ = ScoreTest.sc.server.connection_info()
            ScoreTest.sc.lang.cmd(
                fr"""
                var g;
                TempoClock.default.tempo = 1;
                d = SynthDef("test", {{ |out, freq = 440| OffsetOut.ar(out, SinOsc.ar(freq, 0, 0.2) * Line.kr(1, 0, 0.5, doneAction: Done.freeSelf))}});
                g = [
                    [0.0, [\d_recv, d.asBytes]],
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
                    outputFilePath: "{(tmp_path / sclang_snd).as_posix()}",
                    headerFormat: "AIFF",
                    action: {{ NetAddr("127.0.0.1", {port}).sendMsg('/return', "nrt-done") }}
                );
                """
            )
            self.assertEqual(
                "nrt-done", ScoreTest.sc.server.msg_queues["/return"].get(timeout=4)
            )
            with aifc.open((tmp_path / sclang_snd).as_posix(), "rb") as sclang_wav:
                with aifc.open((tmp_path / sc3nb_snd).as_posix(), "rb") as sc3nb_wav:
                    self.assertEqual(sclang_wav.getparams(), sc3nb_wav.getparams())

            with self.assertWarnsRegex(
                UserWarning,
                "This method currently destroys the time tag if they happend in the past.",
            ):
                messages_sclang = Score.load_file(tmp_path / sclang_osc)
                messages_sc3nb = Score.load_file(tmp_path / sc3nb_osc)

            messages_sclang = next(iter(messages_sclang.values()))
            messages_sc3nb = next(iter(messages_sc3nb.values()))

            gmsg = OSCMessage("/g_new", [1, 0, 0])
            for msg in messages_sclang[:2]:
                self.assertTrue(
                    msg.address == gmsg.address and msg.parameters == gmsg.parameters
                )

            for n, msg in enumerate(messages_sclang[2:]):
                self.assertTrue(
                    msg.address == messages_sc3nb[n].address
                    and msg.parameters == messages_sc3nb[n].parameters
                )
