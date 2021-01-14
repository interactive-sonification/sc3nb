"""Contains classes enabling the easy communication with SuperCollider
within jupyter notebooks
"""

import logging
import warnings

from IPython import get_ipython

import sc3nb.magics

#from .sc_objects.buffer import Buffer
#from .sc_objects.synthdef import SynthDef
#from .sc_objects.node import Synth, Group

from .sc_objects.server import SCServer

#from .osc.osc_communication import OscCommunication
from .sclang import Sclang
#from .tools import (find_executable, parse_pyvars,
#                    remove_comments, replace_vars)
from .process_handling import ProcessTimeout

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())

def startup(start_server=True, start_sclang=True, magic=True, scsynth_options=None):
    """Starts SC, boots scsynth and registers magics

    Keyword Arguments:
        boot {bool} -- if True boot scsynth
                    (default: {True})
        magic {bool} -- if True register jupyter magics
                        (default: {True})

    Returns:
        SC -- Communicates with and controls SuperCollider
    """
    if magic:
        ipy = get_ipython()
        if ipy is not None:
            sc3nb.magics.load_ipython_extension(ipy)

    if SC.default is None:
        SC.default = SC(start_server, start_sclang, scsynth_options)
    else:
        _LOGGER.info("SC already started")
        if start_server:
            SC.default.start_server(scsynth_options)
        if start_sclang:
            SC.default.start_sclang()
    return SC.default


class SC():
    """SC is a class to start SuperCollider language as subprocess
    and control it via a pipe. Communication with scsynth is handled
    by OSC messages via. Jupyter magic commands allow for simple
    execution of SuperCollider code within jupyter notebooks.
    (c) 2016-19 thermann@techfak.uni-bielefeld.de

    Keyword Arguments:
        sclangpath {str} -- Path to sclang
                            (default: {None})

    Raises:
        NotImplementedError -- Raised if
                               unsupported OS is found
    """

    default = None

    def __init__(self,
                 start_server=True,
                 start_sclang=True,
                 scsynth_options=None,
                 console_logging=True):
        self._console_logging = console_logging

        self._server = None
        if start_server:
            self.start_server(scsynth_options=scsynth_options)

        self._sclang = None
        if start_sclang:
            self.start_sclang()

        # connect lang with osc
        #self._sclang.osc = self._server.osc
        #self._sclang.server = self._server
        #self._server._sclang = self._sclang


    def start_sclang(self, sclang_path=None, console_logging=True):
        if self._sclang is None:
            self._sclang = Sclang()
            try:
                self._sclang.start(sclang_path=sclang_path, console_logging=console_logging)
            except ProcessTimeout:
                self._sclang = None
                warnings.warn("starting sclang failed")
                raise
            else:
                if self._server is not None:
                    self._sclang.connect_to_server(self._server)
        else:
            _LOGGER.info("sclang already started")

    def start_server(self, scsynth_path=None, console_logging=True, scsynth_options=None):
        if self._server is None:
            self._server = SCServer(server_options=scsynth_options)
            try:
                self._server.boot(scsynth_path=scsynth_path, console_logging=console_logging)
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
