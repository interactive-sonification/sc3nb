"""Server Volume controls."""


import logging
import warnings
from typing import TYPE_CHECKING, Optional

from sc3nb.helpers import clip, dbamp
from sc3nb.sc_objects.node import AddAction, Synth
from sc3nb.sc_objects.synthdef import SynthDef

if TYPE_CHECKING:
    from sc3nb.sc_objects.server import SCServer


_LOGGER = logging.getLogger(__name__)


class Volume:
    """Server volume controls"""

    def __init__(self, server: "SCServer", min_: int = -90, max_: int = 6) -> None:
        self._server = server
        self._server.add_init_hook(self.send_synthdef)
        self._server.add_init_hook(self.update_synth)

        self.min = min_
        self.max = max_

        self._muted = False
        self._volume = 0.0
        self._lag = 0.1

        self._synth_name: Optional[str] = None

        self._synth: Optional[Synth] = None

    @property
    def muted(self):
        """True if muted."""
        return self._muted

    @muted.setter
    def muted(self, muted: bool):
        if muted:
            self.mute()
        else:
            self.unmute()

    @property
    def volume(self):
        """Volume in dB."""
        return self._volume

    @volume.setter
    def volume(self, volume):
        self._volume = clip(volume, self.min, self.max)
        self.update_synth()

    def mute(self) -> None:
        """Mute audio"""
        self._muted = True
        self.update_synth()

    def unmute(self) -> None:
        """Unmute audio"""
        self._muted = False
        self.update_synth()

    def update_synth(self) -> None:
        """Update volume Synth"""
        amp = 0.0 if self._muted else dbamp(self._volume)
        active = amp != 1.0
        if active:
            if self._server.is_running:
                if self._synth is None:
                    if self._synth_name is None:
                        warnings.warn(
                            "Cannot set volume. Volume SynthDef unknown. Is the default sclang running?"
                        )
                        return
                    controls = {
                        "volumeAmp": amp,
                        "volumeLag": self._lag,
                        "bus": self._server.output_bus.idxs[0],
                    }
                    self._synth = Synth(
                        self._synth_name,
                        add_action=AddAction.AFTER,
                        target=self._server.default_group,
                        controls=controls,
                        server=self._server,
                    )
                else:
                    self._synth.set("volumeAmp", amp)
        else:
            if self._synth is not None:
                self._synth.release()
                self._synth = None

    def send_synthdef(self):
        """Send Volume SynthDef"""
        if self._server.is_running:
            num_channels = self._server.output_bus.num_channels
            synth_def = SynthDef(
                f"sc3nb_volumeAmpControl{num_channels}",
                r"""{ | volumeAmp = 1, volumeLag = 0.1, gate=1, bus |
                    XOut.ar(bus,
                        Linen.kr(gate, releaseTime: 0.05, doneAction:2),
                        In.ar(bus, ^num_channels) * Lag.kr(volumeAmp, volumeLag)
                    );
                }""",
            )
            try:
                self._server.lookup_receiver("sclang")
            except KeyError:
                _LOGGER.info(
                    "Volume SynthDef cannot be send. No sclang receiver known."
                )
            else:
                self._synth_name = synth_def.add(server=self._server)
                assert self._synth_name is not None, "Synth name is None"
