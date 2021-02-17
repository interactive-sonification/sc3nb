"""Collection of Classes and functions for communicating
with SuperCollider within python and jupyter notebooks,
as well as playing recording and visualizing audio
"""

from sc3nb.helpers import *

from sc3nb.sc import startup, SC

from sc3nb.timed_queue import TimedQueue, TimedQueueSC

from sc3nb.osc.osc_communication import build_message, Bundler

from sc3nb.sc_objects.buffer import Buffer
from sc3nb.sc_objects.synthdef import SynthDef
from sc3nb.sc_objects.node import Node, Synth, Group, AddAction
from sc3nb.sc_objects.server import SCServer, ServerOptions, Recorder

def load_ipython_extension(ipython):
    """Load the extension in IPython."""
    from sc3nb.magics import load_ipython_extension as load_extension
    load_extension(ipython)
