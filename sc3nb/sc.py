"""Contains classes enabling the easy communication with SuperCollider
within jupyter notebooks
"""

import logging
import warnings

from typing import Optional, Sequence
from IPython import get_ipython


import sc3nb.magics as magics

from sc3nb.sc_objects.server import SCServer, ServerOptions
from sc3nb.sclang import SCLang
from sc3nb.process_handling import ProcessTimeout, ALLOWED_PARENTS

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())

def startup(start_server: bool = True,
            scsynth_path: Optional[str] = None,
            start_sclang: bool = True,
            sclang_path: Optional[str] = None,
            magic: bool = True,
            scsynth_options: Optional[ServerOptions] = None,
            console_logging: bool = True,
            allowed_parents: Sequence[str] =ALLOWED_PARENTS):
    """Inits SuperCollider (scsynth, sclang) and registers Jupyter magics

    Parameters
    ----------
    start_server : bool, optional
        If True boot scsynth, by default True
    scsynth_path : Optional[str], optional
        Path of scscynth executable, by default None
    start_sclang : bool, optional
        If True start sclang, by default True
    sclang_path : Optional[str], optional
        Path of sclang executable, by default None
    magic : bool, optional
        If True register magics to Jupyter, by default True
    scsynth_options : Optional[ServerOptions], optional
        Options for the server, by default None
    console_logging : bool, optional
        If True write scsynth/sclang output to console, by default True
    allowed_parents : Sequence[str], optional
        Names of parents that are allowed for other instances of
        sclang/scsynth processes, by default ALLOWED_PARENTS

    Returns
    -------
    SC
        SuperCollider Interface class.
    """    
    if magic:
        ipy = get_ipython()
        if ipy is not None:
            magics.load_ipython_extension(ipy)

    if SC.default is None:
        SC.default = SC(start_server=start_server,
                        scsynth_path=scsynth_path,
                        start_sclang=start_sclang,
                        sclang_path=sclang_path,
                        scsynth_options=scsynth_options,
                        console_logging=console_logging,
                        allowed_parents=allowed_parents)
    else:
        _LOGGER.info("SC already started")
        if start_server:
            SC.default.start_server(scsynth_options=scsynth_options,
                                    scsynth_path=scsynth_path,
                                    allowed_parents=allowed_parents)
        if start_sclang:
            SC.default.start_sclang(sclang_path=sclang_path,
                                    allowed_parents=allowed_parents)
    return SC.default


class SC():

    default: Optional["SC"] = None

    def __init__(self,
                 start_server=True,
                 scsynth_path=None,
                 start_sclang=True,
                 sclang_path=None,
                 scsynth_options=None,
                 console_logging=True,
                 allowed_parents=ALLOWED_PARENTS):
        self._console_logging = console_logging
        self._server = None
        self._sclang = None
        if start_server:
            self.start_server(scsynth_path=scsynth_path,
                              scsynth_options=scsynth_options,
                              console_logging=self._console_logging,
                              allowed_parents=allowed_parents)
        if start_sclang:
            self.start_sclang(sclang_path=sclang_path,
                              console_logging=self._console_logging,
                              allowed_parents=allowed_parents)

    def start_sclang(self,
                     sclang_path=None,
                     console_logging=True,
                     allowed_parents=ALLOWED_PARENTS):
        if self._sclang is None:
            self._sclang = SCLang()
            try:
                self._sclang.start(
                    sclang_path=sclang_path,
                    console_logging=console_logging,
                    allowed_parents=allowed_parents)
            except ProcessTimeout:
                self._sclang = None
                warnings.warn("starting sclang failed")
                raise
            else:
                if self._server is not None:
                    self._sclang.connect_to_server(self._server)
        else:
            _LOGGER.info("sclang already started")

    def start_server(self,
                     scsynth_options=None,
                     scsynth_path=None,
                     console_logging=True,
                     allowed_parents=ALLOWED_PARENTS):
        if self._server is None:
            self._server = SCServer(server_options=scsynth_options)
            try:
                self._server.boot(scsynth_path=scsynth_path,
                                  console_logging=console_logging,
                                  allowed_parents=allowed_parents)
            except ProcessTimeout:
                self._server = None
                warnings.warn("starting scsynth failed")
                raise
        else:
            _LOGGER.info("scsynth already started")

    @property
    def server(self):
        if self._server is not None:
            return self._server
        else:
            raise RuntimeWarning("You need to start the SuperCollider Server first")

    @property
    def lang(self):
        if self._sclang is not None:
            return self._sclang
        else:
            raise RuntimeWarning("You need to start the SuperCollider Language (sclang) first")

    @property
    def console_logging(self):
        return self._console_logging

    @console_logging.setter
    def console_logging(self, value):
        if self._server is not None:
            self._server.process.console_logging = value
        if self._sclang is not None:
            self._sclang.process.console_logging = value

    def __del__(self):
        '''Handles clean deletion of object'''
        self.exit()

    def exit(self):
        """Closes SuperCollider and shuts down server
        """
        if self._server is not None and self._server.has_booted and self._server.is_local:
            self._server.quit()
            self._server = None
        if self._sclang is not None:
            self._sclang.kill()
            self._sclang = None
        if self is SC.default:
            SC.default = None

    # TODO what about the MIDI stuff?
    # def midi_ctrl_synth(self, synthname='syn'):
    #     """Set up MIDI control synth

    #     Keyword Arguments:
    #         synthname {str} -- Name of synth
    #                            (default: {'syn'})
    #     """

    #     self.cmd(r"""
    #         MIDIIn.connectAll;
    #         n.free;
    #         n = MIDIFunc.noteOn(
    #             { | level, pitch |
    #                 var amp = ((level-128)/8).dbamp;
    #                 Synth.new(^synthname, [\freq, pitch.midicps, \amp, amp]);
    #                 [pitch, amp].postln
    #             });
    #         """, pyvars={"synthname": synthname})

    # def midi_ctrl_free(self):
    #     """Free MIDI control synth
    #     """

    #     self.cmd("n.free")

    # def midi_gate_synth(self, synthname='syn'):
    #     """Set up MIDI gate synth

    #     Keyword Arguments:
    #         synthname {str} -- Name of synth
    #                            (default: {'syn'})
    #     """

    #     self.cmd(r"""
    #         MIDIIn.connectAll;
    #         q = q ? ();
    #         // q.on.free;
    #         // q.off.free;
    #         // array has one slot per possible MIDI note
    #         q.notes = Array.newClear(128);
    #         q.on = MIDIFunc.noteOn({ |veloc, num, chan, src|
    #             q.notes[num] = Synth.new(
    #                 ^synthname,
    #                 [\freq, num.midicps, \amp, veloc * 0.00315]);
    #         });
    #         q.off = MIDIFunc.noteOff({ |veloc, num, chan, src|
    #             q.notes[num].release;
    #         });
    #         q.freeMIDI = { q.on.free; q.off.free; };
    #         """, pyvars={"synthname": synthname})

    # def midi_gate_free(self):
    #     """Free MIDI gate synth
    #     """
    #     self.cmd("q.on.free; q.off.free")
