"""Collection of Classes and functions for communicating
with SuperCollider within python and jupyter notebooks,
as well as playing recording and visualizing audio
"""

from .sc import startup, SC
from .helpers import ampdb, clip, cpsmidi, dbamp, linlin, midicps
from .timed_queue import TimedQueue, TimedQueueSC
