"""Package for interfacing SuperCollider.

Collection of Classes and functions for communicating
with SuperCollider within python and jupyter notebooks,
as well as playing recording and visualizing audio.

Examples
--------
For example usage please refer to the user guide.
"""


from sc3nb.sc import startup, SC

from sc3nb.sc_objects.server import SCServer, ServerOptions
from sc3nb.sclang import SCLang

from sc3nb.sc_objects.node import Node, Synth, Group, AddAction
from sc3nb.sc_objects.synthdef import SynthDef
from sc3nb.sc_objects.buffer import Buffer
from sc3nb.sc_objects.bus import Bus

from sc3nb.sc_objects.recorder import Recorder

from sc3nb.timed_queue import TimedQueue, TimedQueueSC
from sc3nb.osc.osc_communication import OSCMessage, Bundler

from sc3nb.helpers import linlin, midicps, cpsmidi, clip, dbamp, ampdb


__all__ = [
    "startup",
    "SC",
    "TimedQueue",
    "TimedQueueSC",
    "OSCMessage",
    "Bundler",
    "SCLang",
    "linlin",
    "midicps",
    "cpsmidi",
    "clip",
    "dbamp",
    "ampdb",
    "Buffer",
    "SynthDef",
    "Node",
    "Synth",
    "Group",
    "AddAction",
    "SCServer",
    "ServerOptions",
    "Recorder",
    "Bus",
]


def load_ipython_extension(ipython):
    """Load the extension in IPython."""
    from sc3nb.magics import load_ipython_extension as load_extension

    load_extension(ipython)
