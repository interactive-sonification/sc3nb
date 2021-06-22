"""Classes to run register functions at certain timepoints and run asynchronously"""

import threading
import time
from typing import Any, Callable, Iterable, NoReturn, Union

import numpy as np

import sc3nb
from sc3nb.osc.osc_communication import Bundler, OSCCommunication, OSCMessage


class Event:
    """Stores a timestamp, function and arguments for that function.
    Long running functions can be wrapped inside an own thread

    Parameters
    ----------
    timestamp : float
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
        timestamp: float,
        function: Callable[..., None],
        args: Iterable[Any],
        spawn: bool = False,
    ) -> None:
        if spawn:
            thread = threading.Thread(target=function, args=args)
            function = thread.start
            args = ()
        self.timestamp = timestamp
        self.function = function
        self.args = args

    def execute(self) -> None:
        """Executes function"""
        self.function(*self.args)

    def __eq__(self, other):
        return self.timestamp == other.timestamp

    def __lt__(self, other):
        return self.timestamp < other.timestamp

    def __le__(self, other):
        return self.timestamp <= other.timestamp

    def __repr__(self):
        return "%s: %s" % (self.timestamp, self.function.__name__)


class TimedQueue:
    """Accumulates events as timestamps and functions.

    Executes given functions according to the timestamps

    Parameters
    ----------
    relative_time : bool, optional
        If True, use relative time, by default False
    thread_sleep_time : float, optional
        Sleep time in seconds for worker thread, by default 0.001
    drop_time_threshold : float, optional
        Threshold for execution time of events in seconds.
        If this is exceeded the event will be dropped, by default 0.5
    """

    def __init__(
        self,
        relative_time: bool = False,
        thread_sleep_time: float = 0.001,
        drop_time_threshold: float = 0.5,
    ) -> None:
        self.drop_time_thr = drop_time_threshold
        self.start = time.time() if relative_time else 0
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
        timestamp: float,
        function: Callable[..., None],
        args: Iterable[Any] = (),
        spawn: bool = False,
    ) -> None:
        """Adds event to queue

        Parameters
        ----------
        timestamp : float
            Time (POSIX) when event should be executed
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

        if not callable(function):
            raise TypeError("function argument cannot be called")
        if not isinstance(args, tuple):
            args = (args,)
        new_event = Event(timestamp, function, args, spawn)
        with self.lock:
            self.event_list.append(new_event)
            evlen = len(self.event_list)
            if not self.onset_idx.any():
                idx = 0
            else:
                idx = np.searchsorted(self.onset_idx[:, 0], timestamp)
            self.onset_idx = np.insert(
                self.onset_idx, idx, [timestamp, evlen - 1], axis=0
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
                if event.timestamp <= time.time() - self.start:
                    # execute only if not too old
                    if event.timestamp > time.time() - self.start - self.drop_time_thr:
                        event.execute()
                    self.pop()
                # sleep_time = event_list[0].timestamp - (time.time() - self.start) - 0.001
            time.sleep(sleep_time)

    def __repr__(self):
        return f"<TimedQueue {self.event_list.__repr__()}>"

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
        Sleep time in seconds for worker thread, by default 0.001
    """

    def __init__(
        self,
        server: OSCCommunication = None,
        relative_time: bool = False,
        thread_sleep_time: float = 0.001,
    ):
        super().__init__(relative_time, thread_sleep_time)
        self.server = server or sc3nb.SC.get_default().server

    def put_bundler(self, onset: float, bundler: Bundler) -> None:
        """Add a Bundler to queue

        Parameters
        ----------
        onset : float
            Sending timetag of the Bundler
        bundler : Bundler
            Bundler that will be sent
        """
        self.put(onset, bundler.send)

    def put_msg(
        self, onset: float, msg: Union[OSCMessage, str], msg_params: Iterable[Any]
    ) -> None:
        """Add a message to queue

        Parameters
        ----------
        onset : float
            Sending timetag of the message
        msg : Union[OSCMessage, str]
            OSCMessage or OSC address
        msg_params : Iterable[Any]
            If msg is str, this will be the parameters of the created OSCMessage
        """
        if isinstance(msg, str):
            self.put(onset, self.server.msg, args=(msg, msg_params))
        else:
            self.put(onset, self.server.send, args=(msg,))
