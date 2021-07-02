import time

from sc3nb.helpers import dbamp
from sc3nb.sc_objects.node import Synth
from sc3nb.sc_objects.synthdef import SynthDef
from tests.conftest import SCBaseTest


class VolumeTest(SCBaseTest):

    __test__ = True
    start_sclang = True

    def setUp(self) -> None:
        self.assertIsNotNone(VolumeTest.sc.lang)
        VolumeTest.sc.server.unmute()
        self.assertFalse(VolumeTest.sc.server.muted)
        vol_synth = VolumeTest.sc.server._volume._synth
        if vol_synth is not None:
            vol_synth.wait(timeout=1)
        del vol_synth
        self.assertIsNone(VolumeTest.sc.server._volume._synth)
        self.custom_nodeid = 42
        self.all_synth_args = {"freq": 400, "amp": 0.3, "num": 4, "pan": 0, "lg": 0.1}
        self.synth = Synth("s2", nodeid=self.custom_nodeid)

    def tearDown(self) -> None:
        self.synth.free()
        time.sleep(0.1)

    def test_synth_desc(self):
        num_channels = VolumeTest.sc.server.options.num_output_buses
        self.assertIsNotNone(
            SynthDef.get_description(f"sc3nb_volumeAmpControl{num_channels}")
        )

    def test_set_volume(self):
        volume = -10
        VolumeTest.sc.server.volume = volume
        self.assertEqual(volume, VolumeTest.sc.server.volume)
        vol_synth = VolumeTest.sc.server._volume._synth
        self.assertIn(vol_synth, VolumeTest.sc.server.query_tree().children)
        self.assertAlmostEqual(dbamp(volume), vol_synth.get("volumeAmp"))
        VolumeTest.sc.server.muted = True
        VolumeTest.sc.server.volume = 0
        self.assertAlmostEqual(0, vol_synth.get("volumeAmp"))
        VolumeTest.sc.server.muted = False
        vol_synth.wait(timeout=0.2)
        self.assertNotIn(vol_synth, VolumeTest.sc.server.query_tree().children)
        del vol_synth
        self.assertFalse(VolumeTest.sc.server.muted)
        self.assertIsNone(VolumeTest.sc.server._volume._synth)
