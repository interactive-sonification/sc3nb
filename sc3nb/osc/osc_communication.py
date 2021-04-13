"""OSC communication

Classes and functions to communicate with SuperCollider
using the Open Sound Control (OSC) protocol over UDP
"""

import copy
import errno
import logging
import threading
import time
import warnings
from abc import ABC, abstractmethod
from queue import Empty, Queue
from threading import RLock
from typing import Any, Callable, Dict, Optional, Sequence, Tuple, Union

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_bundle import OscBundle
from pythonosc.osc_bundle_builder import OscBundleBuilder
from pythonosc.osc_message import OscMessage
from pythonosc.osc_message_builder import OscMessageBuilder
from pythonosc.osc_server import OSCUDPServer, ThreadingOSCUDPServer

import sc3nb

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())


def build_message(
    msg_addr: str, msg_args: Optional[Union[Sequence, Any]] = None
) -> OscMessage:
    """Builds pythonsosc OSC message.

    Parameters
    ----------
    msg_addr : str
        SuperCollider address.
    msg_args : None or list or dict
        List of arguments to add to message.

    Returns
    -------
    OscMessage
        Message ready to be sent.

    """
    if msg_args is None:
        msg_args = []
    elif not hasattr(msg_args, "__iter__") or isinstance(msg_args, (str, bytes)):
        msg_args = [msg_args]

    if not msg_addr.startswith("/"):
        msg_addr = "/" + msg_addr

    builder = OscMessageBuilder(address=msg_addr)
    for msg_arg in msg_args:
        builder.add_arg(msg_arg)
    return builder.build()


class Bundler:
    """Class for creating OSCBundles and Bundling of Messages"""

    def __init__(
        self,
        timestamp: float = 0,
        msg: Optional[Union[OscMessage, str]] = None,
        msg_args: Optional[Sequence[Any]] = None,
        server: Optional["OSCCommunication"] = None,
        receiver: Optional[Union[str, Tuple[str, int]]] = None,
        send_on_exit: bool = True,
    ) -> None:
        """Create a Bundler

        Parameters
        ----------
        timestamp : float, optional
            Starting time at which bundle content should be executed.
            If timestamp <= 1e6 it is added to time.time(), by default 0
        msg : OscMessage or str, optional
            OscMessage or message address, by default None
        msg_args : sequence of any type, optional
            Arguments for the message, by default None
        server : OSCCommunication, optional
            OSC server, by default None
        receiver : Union[str, Tuple[str, int]], optional
            Where to send the bundle, by default send to default receiver of server
        send_on_exit : bool, optional
            Wether the bundle is send when using as context manger, by default True
        """
        self.timestamp = timestamp
        self.default_receiver = receiver
        if server is not None:
            self.server = server
        else:
            try:
                self.server = sc3nb.SC.get_default().server
            except RuntimeError:
                self.server = None
        self.contents = []
        self.passed_time = 0.0
        if msg:
            if not isinstance(msg, OscMessage):
                msg = build_message(msg, msg_args)
            self.contents.append(msg)
        self.send_on_exit = send_on_exit

    def wait(self, time_passed: float) -> None:
        """Add time to internal time

        Parameters
        ----------
        time_passed : float
            How much secounds should be passed.
        """
        self.passed_time += time_passed

    def add(self, *params) -> "Bundler":
        """Add a pythonosc OscMessage or OscBundle to this bundle.

        Parameters
        ----------
        params : OscMessage or Bundler or Bundler arguments like
                 (timestamp, msg_addr, msg_args)
                 (timestamp, msg_addr)

        Returns
        -------
        Bundler
            self for chaining
        """
        if len(params) == 1:
            content = params[0]
            if isinstance(content, OscMessage):
                bundler = Bundler(self.passed_time, content)
            elif isinstance(content, Bundler):
                bundler = copy.deepcopy(content)
                if bundler.timestamp < 1e6:
                    bundler.timestamp += self.passed_time
            else:
                raise ValueError(
                    f"Cannot add {content} of type {type(content)}. "
                    f"Needing {OscMessage} or {Bundler}"
                )
            _LOGGER.debug(
                "%s Appending %s to Bundler with time %s",
                self.passed_time,
                bundler,
                bundler.timestamp,
            )
            self.contents.append(bundler)
        else:
            if len(params) == 3:
                timestamp, msg_addr, msg_args = params
                self.add(Bundler(timestamp, msg_addr, msg_args))
            elif len(params) == 2:
                timestamp, msg_addr = params
                self.add(Bundler(timestamp, msg_addr))
            else:
                raise ValueError(f"Invalid parameters {params}")
        return self

    def __deepcopy__(self, memo) -> "Bundler":
        timestamp = self.timestamp
        new_bundler = Bundler(timestamp, server=self.server)
        new_bundler.contents = copy.deepcopy(self.contents)
        return new_bundler

    def build(self, time_offset: Optional[float] = None) -> OscBundle:
        """Build this bundle.

        Parameters
        ----------
        time_offset : Optional[float], optional
            used for recursion, by default None

        Returns
        -------
        OscBundle
            bundle instance for sending
        """
        # if time_offset is None this is the root bundler
        if time_offset is None:
            time_offset = time.time()
        # time to unix time when relative
        if self.timestamp <= 1e6:
            # new time = relative offset (start time) + relative timestamp
            time_offset = time_offset + self.timestamp
        else:
            # absolute time
            time_offset = self.timestamp
        # build bundle
        builder = OscBundleBuilder(time_offset)
        # add contents
        for content in self.contents:
            if isinstance(content, Bundler):
                builder.add_content(content.build(time_offset=time_offset))
            elif isinstance(content, OscMessage):
                builder.add_content(content)
            else:
                ValueError("Couldn't build with unsupported content: {content}")
        return builder.build()

    def send(
        self,
        server: Optional["OSCCommunication"] = None,
        receiver: Tuple[str, int] = None,
        bundled: bool = True,
    ):
        """Send this Bundler.

        Parameters
        ----------
        server : OSCCommunication, optional
            Server instance for sending the bundle.
            If None it will use the server from init
            or try to use sc3nb.SC.get_default().server, by default None
        receiver : Tuple[str, int], optional
            Address (ip, port) to send to, if None it will send the bundle to
            the default receiver of the Bundler
        bundled : bool, optional
            If True this is allowed to be bundled, by default True

        Raises
        ------
        RuntimeError
            When no server could be found.
        """
        if not server:
            server = self.server or sc3nb.SC.get_default().server
        else:
            raise RuntimeError("No server for sending provided.")
        if receiver is None and self.default_receiver is not None:
            receiver = server.lookup_receiver(self.default_receiver)
        server.send(self, receiver=receiver, bundled=bundled)

    def __enter__(self):
        self.server._bundling_lock.acquire(timeout=1)
        # if there is already a bundling bundle set when we have
        # the lock it is from the same thread.
        self.server._bundling_bundles.append(self)
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        if self.server._bundling_bundles.pop() is not self:
            raise RuntimeError("Bundler nesting failed.")
        self.server._bundling_lock.release()
        if exc_type:
            raise RuntimeError("Bundler failed. Check if add is used correctly.")
        if self.send_on_exit:
            self.send(bundled=True)


class MessageHandler(ABC):
    """Base class for Message Handling"""

    @property
    @abstractmethod
    def map_values(self) -> Tuple[str, Callable]:
        """Values used to setup mapping

        Returns
        -------
        Tuple[str, Callable]
            OSC address, corresponding callback
        """

    @abstractmethod
    def put(self, address: str, *args) -> None:
        """Add message to MessageHandler

        Parameters
        ----------
        address : str
            Message address
        """


class MessageQueue(MessageHandler):
    """Queue to retrieve OSC messages send to the corresponding OSC address"""

    def __init__(self, address: str, preprocess: Optional[Callable] = None):
        """Create a new AddressQueue

        Parameters
        ----------
        address : str
            OSC address for this queue
        preprocess : function, optional
            function that will be applied to the value before they are enqueued
             (Default value = None)
        """
        self._address = address
        self.process = preprocess
        self._queue = Queue()
        self._skips = 0

    def put(self, address: str, *args) -> None:
        """Add a message to MessageQueue

        Parameters
        ----------
        address : str
            message address
        """
        if self._address != address:
            _LOGGER.warning(
                "AddressQueue %s: alternative address %s", self._address, address
            )
        if self.process:
            args = self.process(args)
        else:
            if len(args) == 1:
                args = args[0]
        self._queue.put(args)

    @property
    def skips(self) -> int:
        """Counts how many times this queue was not synced"""
        return self._skips

    def skipped(self):
        """Skipp one queue value"""
        self._skips += 1

    @property
    def map_values(self) -> Tuple[str, Callable]:
        """Values needed for dispatcher map call

        Returns
        -------
        tuple
            (OSC address pattern, callback function)
        """
        return self._address, self.put

    def get(self, timeout: float = 5.0, skip: bool = True) -> Any:
        """Returns a value from the queue

        Parameters
        ----------
        timeout : int, optional
            Time in seconds that will be waited on the queue.
             (Default value = 5)
        skip : bool, optional
            If True the queue will skip as many values as `skips`
             (Default value = True)

        Returns
        -------
        obj
            value from queue

        Raises
        ------
        Empty
            If the queue has no value

        """
        if skip:
            while self._skips > 0:
                skipped_value = self._queue.get(block=True, timeout=timeout)
                _LOGGER.warning("AddressQueue: skipped value %s", skipped_value)
                self._skips -= 1
        if self._skips > 0:
            self._skips -= 1
        val = self._queue.get(block=True, timeout=timeout)
        self._queue.task_done()
        return val

    def show(self) -> None:
        """Print the content of the queue."""
        print(list(self._queue.queue))

    def _repr_pretty_(self, p, cycle) -> None:
        if cycle:
            p.text("AddressQueue")
        else:
            p.text(f"AddressQueue {self._address} : {list(self._queue.queue)}")


class MessageQueueCollection(MessageHandler):
    """A collection of MessageQueues that all are send to the same first address."""

    def __init__(self, address: str, sub_addrs: Optional[Sequence[str]] = None):
        """Create a collection of MessageQueues under the same first address

        Parameters
        ----------
        address : str
            first message address that is the same for all MessageQueues
        sub_addrs : Optional[Sequence[str]], optional
            secound message addresses with seperate queues, by default None
            Additional MessageQueues will be created on demand.
        """
        self._address = address
        if sub_addrs is not None:
            self.msg_queues = {
                msg_addr: MessageQueue(msg_addr) for msg_addr in sub_addrs
            }
        else:
            self.msg_queues = {}

    def put(self, address: str, *args) -> None:
        """Add a message to the corresponding MessageQueue

        Parameters
        ----------
        address : str
            first message address
        """
        subaddress, *args = args
        if subaddress not in self.msg_queues:
            self.msg_queues[subaddress] = MessageQueue(subaddress)
            _LOGGER.debug(
                "MessageQueue for %s was created under MessageQueueCollection %s.",
                subaddress,
                self._address,
            )
        self.msg_queues[subaddress].put(subaddress, *args)

    @property
    def map_values(self) -> Tuple[str, Callable]:
        """Values needed for dispatcher map call

        Returns
        -------
        tuple
            (OSC address pattern, callback function)
        """
        return self._address, self.put

    def __contains__(self, item) -> bool:
        return item in self.msg_queues


class OSCCommunicationError(Exception):
    """Exception for OSCCommunication errors."""

    def __init__(self, message, send_message):
        self.message = message
        self.send_message = send_message
        super().__init__(self.message)


class OSCCommunication:
    """Class to send and receive OSC messages and bundles."""

    def __init__(
        self,
        server_ip: str,
        server_port: int,
        default_receiver_ip: str,
        default_receiver_port: int,
    ) -> None:
        """Create a OSC communication server

        Parameters
        ----------
        server_ip : str
            IP address to use for this server
        server_port : int
            port to use for this server
        default_receiver_ip : str
            IP address used for sending by default
        default_receiver_port : int
            port used for sending by default
        """
        self._receivers: Dict[Tuple[str, int], str] = dict()
        self._default_receiver: Tuple[str, int] = (
            default_receiver_ip,
            default_receiver_port,
        )

        # bundling messages support
        self._bundling_lock = RLock()
        self._bundling_bundles = []

        # create server
        osc_server_dispatcher = Dispatcher()
        while True:
            try:
                self._osc_server = ThreadingOSCUDPServer(
                    (server_ip, server_port), osc_server_dispatcher
                )
                self._osc_server_running = True
                _LOGGER.debug(
                    "This OSCCommunication instance is at port: %s", server_port
                )
                break
            except OSError as error:
                if error.errno == errno.EADDRINUSE:
                    server_port += 1

        # start server thread
        self._osc_server_thread = threading.Thread(
            target=self._osc_server.serve_forever
        )
        self._osc_server_thread.daemon = True
        self._osc_server_thread.start()

        # init queues for msg pairs, must be after self._osc_server
        self._msg_queues: Dict[str, MessageQueue] = {}
        self._reply_addresses: Dict[str, str] = {}

    @property
    def osc_server(self) -> OSCUDPServer:
        """Underlying OSC server"""
        return self._osc_server

    def add_msg_pairs(self, msg_pairs: Dict[str, str]) -> None:
        """Add the provided pairs for message receiving.

        Parameters
        ----------
        msg_pairs : dict[str, str], optional
            dict containing user specified message pairs.
            {msg_addr: reply_addr}
        """
        for msg_addr, reply_addr in msg_pairs.items():
            self.add_msg_queue(MessageQueue(reply_addr), msg_addr)

    def add_msg_queue(
        self, msg_queue: MessageQueue, out_addr: Optional[str] = None
    ) -> None:
        """Add a MessageQueue to this servers dispatcher

        Parameters
        ----------
        msg_queue : MessageQueue
            new MessageQueue
        out_addr : Optional[str], optional
            The outgoing message address that belongs to this MessageQeue, by default None
        """
        reply_addr, handler = msg_queue.map_values
        if reply_addr in self._msg_queues or out_addr in self._reply_addresses:
            warnings.warn(f"Overwriting handler for ({out_addr} -> {reply_addr})")
        self._osc_server.dispatcher.map(reply_addr, handler)
        self._msg_queues[reply_addr] = msg_queue
        if out_addr:
            self._reply_addresses[out_addr] = reply_addr

    def add_msg_queue_collection(
        self, msg_queue_collection: MessageQueueCollection
    ) -> None:
        """Add a MessageQueueCollection

        Parameters
        ----------
        msg_queue_collection : MessageQueueCollection
            MessageQueueCollection to be added
        """
        collection_addr, handler = msg_queue_collection.map_values
        self._osc_server.dispatcher.map(collection_addr, handler)
        for msg_addr, msg_queue in msg_queue_collection.msg_queues.items():
            self._msg_queues[collection_addr + msg_addr] = msg_queue
            self._reply_addresses[msg_addr] = collection_addr + msg_addr

    @property
    def msg_queues(self) -> Dict[str, MessageQueue]:
        """Dict with all added MessageQueues

        Returns
        -------
        Dict[str, MessageQueue]
            Queue address, MessageQueue pairs
        """
        return self._msg_queues

    @property
    def reply_addresses(self) -> Dict[str, str]:
        """Dict with all addresses and the replies

        Returns
        -------
        Dict[str, str]
            Outgoing address, incoming address
        """
        return self._reply_addresses

    def _check_sender(self, sender: Tuple[str, int]) -> Union[str, Tuple[str, int]]:
        return self._receivers.get(sender, sender)

    def lookup_receiver(self, receiver: Union[str, Tuple[str, int]]) -> Tuple[str, int]:
        """Reverse lookup the address of a specific receiver

        Parameters
        ----------
        receiver : str
            Receiver name.

        Returns
        -------
        Tuple[str, int]
            Receiver address (ip, port)
        """
        if isinstance(receiver, str):
            return next(
                addr for addr, name in self._receivers.items() if name == receiver
            )
        elif isinstance(receiver, tuple):
            return receiver
        else:
            raise ValueError(f"Incorrect type for receiver ({receiver}).")

    def connection_info(
        self, print_info: bool = True
    ) -> Tuple[Tuple[str, int], Dict[Tuple[str, int], str]]:
        """Get information about the known addresses

        Parameters
        ----------
        print_info : bool, optional
            If True print connection information
             (Default value = True)

        Returns
        -------
        tuple
            containing the address of this sc3nb OSC Server
            and known receivers addresses in a dict with thier names as values

        """
        if print_info:
            receivers_str = ""
            for addr, name in self._receivers.items():
                receivers_str += f'"{name}" at {addr}\n                 '
            print(
                f"This instance is at {self._osc_server.server_address},\n"
                f"Known receivers: {receivers_str}"
            )
        return (self._osc_server.server_address, self._receivers)

    def add_receiver(self, name: str, ip: str, port: int):
        """Adds a receiver with the specified address.

        Parameters
        ----------
        name : str
            Name of receiver.
        ip : str
            IP address of receiver (e.g. "127.0.0.1")
        port : int
            Port of the receiver
        """
        self._receivers[(ip, port)] = name

    def send(
        self,
        package: Union[OscMessage, Bundler, OscBundle],
        bundled: bool = False,
        receiver: Optional[Union[str, Tuple[str, int]]] = None,
        await_reply: bool = True,
        timeout: float = 5.0,
    ) -> Any:
        """Sends OSC packet

        Parameters
        ----------
        package : OscMessage or OscBundle or Bundler
            Object with `dgram` attribute.
        bundled : bool, optional
            If True it is allowed to bundle the content with bundling, by default False
        receiver : str or Tuple[str, int], optional
            Where to send the packet, by default send to default receiver
        await_reply : bool, optional
            If True and content is a OscMessage send message and wait for reply
            otherwise send the message and return None directly, by default True
        timeout : int, optional
            timeout in seconds for reply, by default 5

        Returns
        -------
        None or reply
            None if no reply was received or awaited else reply.

        Raises
        ------
        ValueError
            When the provided package is not supported.
        OSCCommunicationError
            When the handling of a message fails.
        """
        # bundling
        if bundled:
            with self._bundling_lock:
                if self._bundling_bundles:
                    self._bundling_bundles[-1].add(package)
                    return

        receiver_address = self._default_receiver
        if receiver is not None:
            receiver_address = self.lookup_receiver(receiver)

        try:
            # Bundler needs to be build, this ensures that
            # relative timings are calculated just now
            if isinstance(package, Bundler):
                datagram = package.build().dgram
            else:
                datagram = package.dgram
        except AttributeError as error:
            raise ValueError(
                f"Package '{package}' not supported. It needs a dgram Attribute."
            ) from error

        self._osc_server.socket.sendto(datagram, receiver_address)

        if isinstance(package, OscMessage):
            msg = package
            # logging
            if _LOGGER.isEnabledFor(logging.INFO):
                msg_params_str = str(msg.params)
                if (
                    not _LOGGER.isEnabledFor(logging.DEBUG)
                    and len(str(msg.params)) > 55
                ):
                    msg_params_str = str(msg.params)[:55] + ".."
                _LOGGER.debug(
                    "send to %s : %s %s",
                    self._check_sender(receiver_address),
                    msg.address,
                    msg_params_str,
                )
            # handling
            reply_addr = self.get_reply_address(msg.address)
            try:
                if reply_addr is not None and reply_addr in self._msg_queues:
                    if await_reply:
                        return self._msg_queues[reply_addr].get(timeout, skip=True)
                    else:
                        self._msg_queues[reply_addr].skipped()
            except (Empty, TimeoutError) as error:
                if isinstance(error, Empty):
                    message = (
                        f"Failed to get reply at '{reply_addr}' "
                        f"after '{msg.address}' message to "
                    )
                elif isinstance(error, TimeoutError):
                    message = f"Timed out after '{msg.address}' message to "
                else:
                    message = f"Error when sending '{msg.address}' message to "
                message += f"{self._check_sender(receiver_address)}"
                raise OSCCommunicationError(message, msg) from error

        elif isinstance(package, OscBundle):
            # logging
            if _LOGGER.isEnabledFor(logging.INFO):
                _LOGGER.info(
                    "send to %s : %s contents size %s ",
                    self._check_sender(receiver_address),
                    package,
                    len(package._contents),
                )
        else:
            _LOGGER.info("send to %s : %s", receiver, package)

    def get_reply_address(self, msg_address: str) -> Optional[str]:
        """Get the corresponding reply address for the given address

        Parameters
        ----------
        msg_address : str
            outgoing message address

        Returns
        -------
        str or None
            Corresponding reply address if available
        """
        return self._reply_addresses.get(msg_address, None)

    def msg(
        self,
        msg_addr: str,
        msg_args: Optional[Sequence] = None,
        bundled: bool = False,
        receiver: Optional[Tuple[str, int]] = None,
        await_reply: bool = True,
        timeout: float = 5,
    ) -> Optional[Any]:
        """Creates and sends OSC message over UDP.

        Parameters
        ----------
        msg_addr : str
            SuperCollider address
        msg_args : Optional[Sequence], optional
            List of arguments to add to message, by default None
        bundled : bool, optional
            If True it is allowed to bundle the content with bundling, by default False
        receiver : tuple[str, int], optional
            (IP address, port) to send the message, by default send to default receiver
        await_reply : bool, optional
            If True send message and wait for reply
            otherwise send the message and return directly, by default True
        timeout : float, optional
            timeout in seconds for reply, by default 5

        Returns
        -------
        obj
            reply if await_reply and there is a reply for this
        """
        return self.send(
            build_message(msg_addr, msg_args),
            bundled=bundled,
            receiver=receiver,
            await_reply=await_reply,
            timeout=timeout,
        )

    def bundler(
        self,
        timestamp: float = 0,
        msg: Optional[Union[OscMessage, str]] = None,
        msg_args: Optional[Sequence[Any]] = None,
        send_on_exit: bool = True,
    ) -> Bundler:
        """Generate a Bundler.

        This allows the user to easly add messages/bundles and send it.

        Parameters
        ----------
        timestamp : int
            Time at which bundle content should be executed.
            If timestamp <= 1e6 it is added to time.time().
        msg : OscMessage or str, optional
            OscMessage or message address, by default None
        msg_args : sequence of any type, optional
            Arguments for the message, by default None
        send_on_exit : bool, optional
            Wether the bundle is send when using as context manger, by default True

        Returns
        -------
        Bundler
            bundler for OSC bundling.
        """
        return Bundler(
            timestamp=timestamp,
            msg=msg,
            msg_args=msg_args,
            server=self,
            send_on_exit=send_on_exit,
        )

    def quit(self) -> None:
        """Shuts down the sc3nb OSC server"""
        if self._osc_server_running:
            self._osc_server.shutdown()
            self._osc_server.server_close()
            self._osc_server_running = False
