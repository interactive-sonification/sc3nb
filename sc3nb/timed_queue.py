"""Classes to run register functions at certain timepoints
and run asynchronously
"""

import threading
import time

import numpy as np


class Event():
    """Stores a timestamp, function and arguments for that function.
    Long running functions can be wrapped inside an own thread

    Arguments:
        timetag {int} -- Time event should be executed
        function {[type]} -- Function to be executed
        args {[type]} -- Arguments for function

    Keyword Arguments:
        spawn {bool} -- if True, create new sub-thread
                        for function (default: {False})
    """

    def __init__(self, timetag, function, args, spawn=False):
        if spawn:
            thread = threading.Thread(target=function, args=args)
            function = thread.start
            args = ()

        self.timetag = timetag
        self.function = function
        self.args = args

    def execute(self):
        """Executes function
        """

        self.function(*self.args)

    def __eq__(self, other):
        return self.timetag == other.timetag

    def __lt__(self, other):
        return self.timetag < other.timetag

    def __le__(self, other):
        return self.timetag <= other.timetag

    def __repr__(self):
        return '%s: %s' % (self.timetag, self.function.__name__)


class TimedQueue():
    """Accumulates events as timestamps and functions. Executes given
    functions according to the timestamps

    Keyword Arguments:
        relative_time {bool} -- if True, use relative
                                time (default: {False})
        thread_sleep_time {float} -- Sleep time for
                                     worker thread
                                     (default: {0.001})
    """

    def __init__(self, relative_time=False, thread_sleep_time=0.001, drop_time_thr=0.5):

        self.drop_time_thr = drop_time_thr
        if relative_time:
            self.start = time.time()
        else:
            self.start = 0

        self.onset_idx = np.empty((0, 2))
        self.event_list = []
        self.close_event = threading.Event()

        self.lock = threading.Lock()

        self.thread = threading.Thread(target=self.__worker, args=(
            thread_sleep_time, self.close_event))  # , daemon=True)

        self.thread.start()

    def close(self):
        """Closes event processing without waiting for
        pending events to complete
        """

        self.close_event.set()
        self.thread.join()

    def join(self):
        """Closes event processing after waiting for
        pending events to complete
        """

        self.complete()
        self.close_event.set()
        self.thread.join()

    def complete(self):
        """Blocks until all pending events have completed
        """

        while self.event_list:
            time.sleep(0.01)

    def put(self, timetag, function, args=(), spawn=False):
        """Adds event to queue

        Arguments:
            timetag {int} -- Time when event should be
                             executed
            function {callable} -- Function to be executed

        Keyword Arguments:
            args {tuple} -- Arguments to be passed to function
                            (default: {()})
            spawn {bool} -- if True, create new sub-thread
                            for function (default: {False})

        Raises:
            TypeError -- raised if function is not callable
        """

        if not hasattr(function, '__call__'):
            raise TypeError('function argument cannot be called')
        if not isinstance(args, tuple):
            args = (args,)
        new_event = Event(timetag, function, args, spawn)
        with self.lock:
            self.event_list.append(new_event)
            evlen = len(self.event_list)
            if not self.onset_idx.any():
                idx = 0
            else:
                idx = np.searchsorted(self.onset_idx[:, 0], timetag)
            self.onset_idx = np.insert(
                self.onset_idx, idx, [timetag, evlen - 1], axis=0)

    def get(self):
        """Get latest event from queue and remove event

        Returns:
            Event -- Latest event
        """

        event = self.peek()
        self.pop()
        return event

    def peek(self):
        """Look up latest event from queue

        Returns:
            Event -- latest event
        """

        with self.lock:
            return self.event_list[int(self.onset_idx[0][1])]

    def empty(self):
        """Checks if queue is empty

        Returns:
            bool -- True if queue if empty
        """

        with self.lock:
            return bool(self.event_list)

    def pop(self):
        """Removes latest event from queue
        """

        with self.lock:
            event_idx = int(self.onset_idx[0][1])
            self.onset_idx = self.onset_idx[1:]
            # remove 1 from all idcs after popped event
            self.onset_idx[:, 1][self.onset_idx[:, 1] > event_idx] -= 1
            del self.event_list[event_idx]

    def __worker(self, sleep_time, close_event):
        """Worker function to process events"""
        while True:
            if close_event.is_set():
                break
            if self.event_list:
                event = self.peek()
                if event.timetag <= time.time() - self.start:
                    if event.timetag > time.time() - self.start - self.drop_time_thr:  # only if not too old
                        event.execute()
                    self.pop()
                # sleep_time = event_list[0].timetag - (time.time() - self.start) - 0.001
            time.sleep(sleep_time)

    def __repr__(self):
        return self.event_list.__repr__()


class TimedQueueSC(TimedQueue):

    def __init__(self, sc, relative_time=False, thread_sleep_time=0.001):
        super().__init__(relative_time, thread_sleep_time)

        self.sc = sc

    def put_bundle(self, onset, timetag, address, args, sclang=False):
        self.put(onset, self.sc.bundle, args=(timetag, address, args, sclang))

    def put_msg(self, onset, address, args, sclang=False):
        self.put(onset, self.sc.msg, args=(address, args, sclang))

    def elapse(self, time_delta):
        self.start += time_delta
