"""Classes to run register functions at certain timepoints and run asynchronously"""

import threading
import time
from typing import Any, Callable, Iterable, NoReturn, Union

import numpy as np
from pythonosc.osc_message import OscMessage

import sc3nb
from sc3nb.osc.osc_communication import Bundler, OSCCommunication


class Event:
    """Stores a timestamp, function and arguments for that function.
    Long running functions can be wrapped inside an own thread

    Parameters
    ----------
    timetag : int
        Time event should be executed
    function : Callable[..., None]
        Function to be executed
    args : Iterable[Any]
        Arguments for function
    spawn : bool, optional
        if True, create new thread for function, by default False
    """

    def __init__(
        self,
        timetag: int,
        function: Callable[..., None],
        args: Iterable[Any],
        spawn: bool = False,
    ) -> None:
        if spawn:
            thread = threading.Thread(target=function, args=args)
            function = thread.start
            args = ()
        self.timetag = timetag
        self.function = function
        self.args = args

    def execute(self) -> None:
        """Executes function"""
        self.function(*self.args)

    def __eq__(self, other):
        return self.timetag == other.timetag

    def __lt__(self, other):
        return self.timetag < other.timetag

    def __le__(self, other):
        return self.timetag <= other.timetag

    def __repr__(self):
        return "%s: %s" % (self.timetag, self.function.__name__)


class TimedQueue:
    """Accumulates events as timestamps and functions.

    Executes given functions according to the timestamps

    Parameters
    ----------
    relative_time : bool, optional
        If True, use relative time, by default False
    thread_sleep_time : float, optional
        Sleep time for worker thread, by default 0.001
    drop_time_threshold : float, optional
        Threshold for execution time of events.
        If this is exceeded the event will be dropped, by default 0.5
    """

    def __init__(
        self,
        relative_time: bool = False,
        thread_sleep_time: float = 0.001,
        drop_time_threshold: float = 0.5,
    ) -> None:
        self.drop_time_thr = drop_time_threshold
        if relative_time:
            self.start = time.time()
        else:
            self.start = 0

        self.onset_idx = np.empty((0, 2))
        self.event_list = []
        self.close_event = threading.Event()

        self.lock = threading.Lock()

        self.thread = threading.Thread(
            target=self.__worker, args=(thread_sleep_time, self.close_event)
        )  # , daemon=True)

        self.thread.start()

    def close(self) -> None:
        """Closes event processing without waiting for pending events"""
        self.close_event.set()
        self.thread.join()

    def join(self) -> None:
        """Closes event processing after waiting for pending events"""
        self.complete()
        self.close_event.set()
        self.thread.join()

    def complete(self) -> None:
        """Blocks until all pending events have completed"""
        while self.event_list:
            time.sleep(0.01)

    def put(
        self,
        timetag: int,
        function: Callable[..., None],
        args: Iterable[Any] = (),
        spawn: bool = False,
    ) -> None:
        """Adds event to queue

        Parameters
        ----------
        timetag : int
            Time when event should be executed
        function : Callable[..., None]
            Function to be executed
        args : Iterable[Any], optional
            Arguments to be passed to function, by default ()
        spawn : bool, optional
            if True, create new sub-thread for function, by default False

        Raises
        ------
        TypeError
            raised if function is not callable
        """

        if not hasattr(function, "__call__"):
            raise TypeError("function argument cannot be called")
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
                self.onset_idx, idx, [timetag, evlen - 1], axis=0
            )

    def get(self) -> Event:
        """Get latest event from queue and remove event

        Returns
        -------
        Event
            Latest event
        """
        event = self.peek()
        self.pop()
        return event

    def peek(self) -> Event:
        """Look up latest event from queue

        Returns
        -------
        Event
            Latest event
        """
        with self.lock:
            return self.event_list[int(self.onset_idx[0][1])]

    def empty(self) -> bool:
        """Checks if queue is empty

        Returns
        -------
        bool
            True if queue if empty
        """
        with self.lock:
            return bool(self.event_list)

    def pop(self) -> None:
        """Removes latest event from queue"""
        with self.lock:
            event_idx = int(self.onset_idx[0][1])
            self.onset_idx = self.onset_idx[1:]
            # remove 1 from all idcs after popped event
            self.onset_idx[:, 1][self.onset_idx[:, 1] > event_idx] -= 1
            del self.event_list[event_idx]

    def __worker(self, sleep_time: float, close_event: threading.Event) -> NoReturn:
        """Worker function to process events"""
        while True:
            if close_event.is_set():
                break
            if self.event_list:
                event = self.peek()
                if event.timetag <= time.time() - self.start:
                    # execute only if not too old
                    if event.timetag > time.time() - self.start - self.drop_time_thr:
                        event.execute()
                    self.pop()
                # sleep_time = event_list[0].timetag - (time.time() - self.start) - 0.001
            time.sleep(sleep_time)

    def __repr__(self):
        return self.event_list.__repr__()

    def elapse(self, time_delta: float) -> None:
        """Add time delta to the current queue time.

        Parameters
        ----------
        time_delta : float
            Additional time
        """
        self.start += time_delta


class TimedQueueSC(TimedQueue):
    """Timed queue with OSC communication.

    Parameters
    ----------
    server : OSCCommunication, optional
        OSC server to handle the bundlers and messsages, by default None
    relative_time : bool, optional
        If True, use relative time, by default False
    thread_sleep_time : float, optional
        Sleep time for worker thread, by default 0.001
    """

    def __init__(
        self,
        server: OSCCommunication = None,
        relative_time: bool = False,
        thread_sleep_time: float = 0.001,
    ):
        super().__init__(relative_time, thread_sleep_time)
        self.server = server or sc3nb.SC.get_default().server

    def put_bundler(self, onset: int, bundler: Bundler) -> None:
        """Add a Bundler to queue

        Parameters
        ----------
        onset : int
            Sending timetag of the Bundler
        bundler : Bundler
            Bundler that will be send
        """
        self.put(onset, bundler.send)

    def put_msg(
        self, onset: int, msg: Union[OscMessage, str], args: Iterable[Any]
    ) -> None:
        """Add a message to queue

        Parameters
        ----------
        onset : int
            Sending timetag of the message
        msg : Union[OscMessage, str]
            OscMessage or OSC address
        args : Iterable[Any]
            If msg is str, this will be the arguments of the created OscMessage
        """
        if isinstance(msg, str):
            self.put(onset, self.server.msg, args=(msg, args))
        else:
            self.put(onset, self.server.send, args=(msg,))
