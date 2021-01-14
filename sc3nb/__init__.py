"""Collection of Classes and functions for communicating
with SuperCollider within python and jupyter notebooks,
as well as playing recording and visualizing audio
"""

from .helpers import *

from .sc import startup, SC

from .timed_queue import TimedQueue, TimedQueueSC

from .osc.osc_communication import build_message, Bundler

from .sc_objects.buffer import Buffer
from .sc_objects.synthdef import SynthDef
from .sc_objects.node import Node, Synth, Group, AddAction
from .sc_objects.server import SCServer, ServerOptions

def load_ipython_extension(ipython):
    """Load the extension in IPython."""
    from sc3nb.magics import load_ipython_extension as load_extension
    load_extension(ipython)
