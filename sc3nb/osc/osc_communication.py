"""OSC communication

Classes and functions to communicate with SuperCollider
using the Open Sound Control (OSC) protocol over UDP
"""

import errno
import logging
import threading
import time
import copy

from queue import Empty, Queue

from random import randint
from pythonosc import (dispatcher, osc_server,
                       osc_bundle_builder, osc_message_builder,
                       osc_bundle, osc_message)

import sc3nb
from sc3nb.osc.parsing import parse_sclang_osc_packet


_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())

SCSYNTH_DEFAULT_PORT = 57110
SCLANG_DEFAULT_PORT = 57120

OSCCOM_DEFAULT_PORT = 57130

ASYNC_MSGS = [
    "/quit",    # Master
    "/notify",
    "/d_recv",  # Synth Def load SynthDefs
    "/d_load",
    "/d_loadDir",
    "/b_alloc",  # Buffer Commands
    "/b_allocRead",
    "/b_allocReadChannel",
    "/b_read",
    "/b_readChannel",
    "/b_write",
    "/b_free",
    "/b_zero",
    "/b_gen",
    "/b_close"
]

MSG_PAIRS = {
    # Master
    "/status": "/status.reply",
    "/sync": "/synced",
    "/version": "/version.reply",
    # Synth Commands
    "/s_get": "/n_set",
    "/s_getn": "/n_setn",
    # Group Commands
    "/g_queryTree": "/g_queryTree.reply",
    # Node Commands
    "/n_query": "/n_info",
    # Buffer Commands
    "/b_query":  "/b_info",
    "/b_get":  "/b_set",
    "/b_getn":  "/b_setn",
    # Control Bus Commands
    "/c_get":  "/c_set",
    "/c_getn":  "/c_setn"
}


#def _add_msg(self, msg_addr, msg_args):
#    """Add a pythonsosc OscMessage to this bundle.
#
#    Parameters
#    ----------
#    msg_addr : str
#        SuperCollider address.
#    msg_args : list
#        List of arguments to add to message.
#
#    Returns
#    -------
#    self
#        for call chaining
#    """
#    msg = build_message(msg_addr, msg_args)
#    self.add_content(msg)
#    return self


#osc_bundle_builder.OscBundleBuilder.add_msg = _add_msg


#def _send(self, osc=None, sclang=False):
#    if self.osc and not osc:
#        self.osc.send(self.build(), sclang=sclang)
#    elif osc:
#        osc.send(self.build(), sclang=sclang)
#    else:
#        RuntimeError("No OSC instance for sending.")


#osc_bundle_builder.OscBundleBuilder.send = _send


#def _add(self, content):
#    if isinstance(content, osc_bundle_builder.OscBundleBuilder):
#        #if content._timestamp <= 1e6:
#        #    content._timestamp += self._timestamp
#        content = content.build()
#    self.add_content(content)
#    return self


#osc_bundle_builder.OscBundleBuilder.add = _add


# def bundle_builder(timestamp, msg_addr=None, msg_args=None):
#     """Builds pythonsosc OSC bundle

#     Parameters
#     ----------
#     timestamp : int
#         Time at which bundle content should be executed.
#         If timestamp < 1e6 it is added to time.time().
#     msg_addr : str
#         SuperCollider address.
#     msg_args : list
#         List of arguments to add to message.

#     Returns
#     -------
#     OscBundle
#         Bundle ready to be sent.

#     """
#    if msg_args is None:
#        msg_args = []

#    if timestamp == 0:
#        timestamp = osc_types.IMMEDIATELY
#    elif timestamp < 1e6:
#        timestamp = time.time() + timestamp
#    builder = osc_bundle_builder.OscBundleBuilder(timestamp)
#    if msg_addr:
#        msg = build_message(msg_addr, msg_args)
#        builder.add_content(msg)
#    return builder


class Bundler():

    def __init__(self, timestamp=0, msg=None, msg_args=None, server=None, send_on_exit=True):
        self.timestamp = timestamp
        if server is not None:
            self.server = server
        elif sc3nb.SC.default:
            self.server = sc3nb.SC.default.server
        else:
            self.server = None
        self.contents = []
        self.passed_time = 0.0
        if msg:
            if not isinstance(msg, osc_message.OscMessage):
                msg = build_message(msg, msg_args)
            self.contents.append(msg)
        self.send_on_exit = send_on_exit

    def wait(self, time_passed):
        self.passed_time += time_passed

    def add(self, *params):
        """Add a pythonosc OscMessage or OscBundle to this bundle.

        Parameters
        ----------
        args : OscMessage or Bundler or Bundler arguments as tuple like
               (timestamp, msg_addr, msg_args)
               (timestamp, msg_addr)

        Returns
        -------
        Bundler
            self for chaining
        """
        if len(params) == 1:
            content = params[0]
            if isinstance(content, osc_message.OscMessage):
                bundler = Bundler(self.passed_time, content)
            elif isinstance(content, Bundler):
                bundler = copy.deepcopy(content)
                if bundler.timestamp < 1e6:
                    bundler.timestamp += self.passed_time
            else:
                raise ValueError(f"Cannot add {content} of type {type(content)}. "
                                 f"Needing {osc_message.OscMessage} or {Bundler}")
            _LOGGER.debug("%s Appending %s to Bundler with time %s", self.passed_time, bundler, bundler.timestamp)
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

    def __deepcopy__(self, memo):
        timestamp = self.timestamp
        new_bundler = Bundler(timestamp, server=self.server)
        new_bundler.contents = copy.deepcopy(self.contents)
        return new_bundler

    def build(self, time_offset=None):
        """Build this bundle.

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
        builder = osc_bundle_builder.OscBundleBuilder(time_offset)
        # add contents
        for content in self.contents:
            if isinstance(content, Bundler):
                builder.add_content(content.build(time_offset=time_offset))
            elif isinstance(content, osc_message.OscMessage):
                builder.add_content(content)
            else:
                ValueError()
        return builder.build()

    def send(self, server=None, sclang=False, bundled=True):
        """Build and send this bundle.

        Parameters
        ----------
        server: SCServer
            Server instance for sending the bundle.
            If None it will use the server from init
            or try to use sc3nb.SC.default.server
        sclang: bool, default False
            If True it will send to the sclang of the server
            instead.
        """
        if not server:
            server = self.server or sc3nb.SC.default.server
        if server:
            server.send(self.build(), sclang=sclang, bundled=bundled)
        else:
            RuntimeError("No server for sending provided.")

    def __enter__(self):
        self.server._bundling_bundle = self
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        self.server._bundling_bundle = None
        if exc_type:
            raise RuntimeError("Bundler failed. Check if add is used correctly.")
        if self.send_on_exit:
            self.send()


def build_message(msg_addr, msg_args=None):
    """Builds pythonsosc OSC message.

    Parameters
    ----------
    msg_addr : str
        SuperCollider address.
    msg_args : list
        List of arguments to add to message.

    Returns
    -------
    OscMessage
        Message ready to be sent.

    """

    if msg_args is None:
        msg_args = []
    elif not hasattr(msg_args, '__iter__') or isinstance(msg_args, (str, bytes)):
        msg_args = [msg_args]

    if not msg_addr.startswith('/'):
        msg_addr = '/' + msg_addr

    builder = osc_message_builder.OscMessageBuilder(address=msg_addr)
    for msg_arg in msg_args:
        builder.add_arg(msg_arg)
    return builder.build()


class AddressQueue():
    """Queue to retrieve OSC messages send to the corresponding OSC address"""

    def __init__(self, address, preprocess=None):
        """Create a new AddressQueue

        Parameters
        ----------
        address : str
            OSC address for this queue
        preprocess : function, optional
            function that will be applied to the value before they are enqueued
             (Default value = None)
        """
        self.address = address
        self.process = preprocess
        self.queue = Queue()
        self._skips = 0

    def _put(self, address, *args):
        if self.address != address:
            _LOGGER.info(
                "AddressQueue %s: alternative address %s", self.address, address)
        if self.process:
            args = self.process(args)
        else:
            if len(args) == 1:
                args = args[0]
        self.queue.put(args)

    @property
    def skips(self):
        """Counts how many times this queue was not synced"""
        return self._skips

    @property
    def map_values(self):
        """Values needed for dispatcher map call

        Returns
        -------
        tuple
            (OSC address pattern, callback function)
        """
        return self.address, self._put

    def get(self, timeout=5, skip=False):
        """Returns a value from the queue

        Parameters
        ----------
        timeout : int, optional
            Time in seconds that will be waited on the queue.
             (Default value = 5)
        skip : bool, optional
            If True the queue will skip as many values as `skips`
             (Default value = False)

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
                skipped_value = self.queue.get(block=True, timeout=timeout)
                _LOGGER.warning("AddressQueue: skipped value %s", skipped_value)
                self._skips -= 1
        if self._skips > 0:
            self._skips -= 1
        val = self.queue.get(block=True, timeout=timeout)
        self.queue.task_done()
        return val

    def show(self):
        """Print the content of the queue."""
        print(list(self.queue.queue))

    def _repr_pretty_(self, p, cycle):
        if cycle:
            p.text('AddressQueue')
        else:
            p.text(f"AddressQueue {self.address} : {list(self.queue.queue)}")


def preprocess_return(value):
    """Preprocessing function for /return values

    Parameters
    ----------
    value : tuple
        return data

    Returns
    -------
    obj
        data

    """
    if len(value) == 1:
        value = value[0]
        if isinstance(value, bytes):
            value = parse_sclang_osc_packet(value)
    return value


class OscCommunication():
    """Class to send and receive OSC messages and bundles."""

    def __init__(self, server_ip='127.0.0.1', server_port=OSCCOM_DEFAULT_PORT,
                 sclang_ip='127.0.0.1', sclang_port=SCLANG_DEFAULT_PORT,
                 scsynth_ip='127.0.0.1', scsynth_port=SCSYNTH_DEFAULT_PORT):
        print("Starting OscCommunication...")

        # set SuperCollider addresses
        self.set_sclang(sclang_ip, sclang_port)
        self.set_scsynth(scsynth_ip, scsynth_port)

        # start server
        server_dispatcher = dispatcher.Dispatcher()
        while True:
            try:
                self.server = osc_server.ThreadingOSCUDPServer(
                    (server_ip, server_port), server_dispatcher)
                print("This OscCommunication instance is at port: {}"
                      .format(server_port))
                break
            except OSError as error:
                if error.errno == errno.EADDRINUSE:
                    server_port += 1

        # set known messages
        self.async_msgs = ASYNC_MSGS
        self.msg_pairs = MSG_PAIRS

        # init queues for msg pairs
        self.msg_queues = {}
        self.update_msg_queues()

        # init special msg queues
        self.returns = AddressQueue("/return", preprocess_return)
        server_dispatcher.map(*self.returns.map_values)

        # As /done messages have no purpose for us at this point
        # we don't collect /done messages
        self.dones = AddressQueue("/done")
        server_dispatcher.map(*self.dones.map_values)

        # set logging handlers
        server_dispatcher.map("/fail", self._warn, needs_reply_address=True)
        server_dispatcher.map("/*", self._log, needs_reply_address=True)

        self.server_thread = threading.Thread(
            target=self.server.serve_forever)
        self.server_thread.daemon = True
        self.server_thread.start()

        print("Done.")

    def update_msg_queues(self, new_msg_pairs=None):
        """Update the queues used for message receiving.

        This method will check for all `msg_pairs` if there is an AddressQueue
        already created and if it is missing it will create one.

        Parameters
        ----------
        new_msg_pairs : dict, optional
            dict containing user specified message pairs.
            This will be added to `msg_pairs`
             (Default value = None)

        """
        if new_msg_pairs:
            self.msg_pairs.update(new_msg_pairs)
        for msg_addr, response_addr in self.msg_pairs.items():
            if msg_addr not in self.msg_queues:
                addr_queue = AddressQueue(response_addr)
                self.server.dispatcher.map(*addr_queue.map_values)
                self.msg_queues[msg_addr] = addr_queue

    def _check_sender(self, sender):
        if sender == self.sclang_address:
            sender = "sclang"
        elif sender == self.scsynth_address:
            sender = "scsynth"
        return sender

    def _log(self, sender, *args):
        if len(str(args)) > 55:
            args_str = str(args)[:55] + ".."
        else:
            args_str = str(args)
        _LOGGER.info("osc msg received from %s: %s",
                     self._check_sender(sender), args_str)

    def _warn(self, sender, *args):
        _LOGGER.warning("Error from %s: %s",
                        self._check_sender(sender), args)

    def set_sclang(self, sclang_ip='127.0.0.1',
                   sclang_port=SCLANG_DEFAULT_PORT):
        """Sets the sclang address.

        Parameters
        ----------
        sclang_ip : str, optional
            IP of sclang
             (Default value = '127.0.0.1')
        sclang_port : int, optional
            port of sclang
             (Default value = SCLANG_DEFAULT_PORT)

        """
        self.sclang_address = (sclang_ip, sclang_port)

    def set_scsynth(self, scsynth_ip='127.0.0.1',
                    scsynth_port=SCSYNTH_DEFAULT_PORT):
        """Sets the scsynth address.

        Parameters
        ----------
        scsynth_ip : str, optional
            IP of scsynth
             (Default value = '127.0.0.1')
        scsynth_port : int, optional
            port of scsynth
             (Default value = SCSYNTH_DEFAULT_PORT)

        """
        self.scsynth_address = (scsynth_ip, scsynth_port)

    def get_connection_info(self, print_info=True):
        """Get information about the address of sc3nb, sclang and scsynth

        Parameters
        ----------
        print_info : bool, optional
            If True print connection information
             (Default value = True)

        Returns
        -------
        tuple
            containing the sc3nb, sclang and scsynth addresses.

        """
        if print_info:
            print("sc3nb {}\nsclang {}\nscsynth {}"
                  .format(self.server.server_address,
                          self.sclang_address, self.scsynth_address))
        return (self.server.server_address,
                self.sclang_address, self.scsynth_address)

    def send(self, content, server_address=None, sclang=False, sync=True, timeout=5):
        """Sends OSC message or bundle to sclang or scsnyth

        Parameters
        ----------
        content : OscMessage or OscBundle
            Object with `dgram` attribute.
        server_address: tuple(ip, port), optional
            Address of the receiving osc server.
            If None, it will send to default osc server.
        sclang : bool
            If True sends msg to sclang else sends msg to scsynth.
        sync : bool, optional
            If True and content is a OscMessage send message and wait for sync or response
            otherwise send the message and return directly.
             (Default value = True)
        timeout : int, optional
            timeout in seconds for sync and response.
             (Default value = 5)

        """
        if server_address:
            receiver = server_address
        elif sclang:  # sclang overwrites, specific server_address
            receiver = self.sclang_address
        else:
            receiver = self.scsynth_address

        self.server.socket.sendto(content.dgram, receiver)

        # TODO add async stuff for completion message etc.

        if isinstance(content, osc_message.OscMessage):
            msg = content
            # logging
            if _LOGGER.isEnabledFor(logging.INFO):
                if len(str(msg.params)) > 55:
                    msg_params_str = str(msg.params)[:55] + ".."
                elif _LOGGER.isEnabledFor(logging.DEBUG):
                    msg_params_str = str(msg.params)
                _LOGGER.debug("send to %s : %s %s", receiver, msg.address, msg_params_str)
            # handling
            try:
                if msg.address in self.msg_pairs:
                    if sync:
                        return self.msg_queues[msg.address].get(timeout, skip=True)
                    else:
                        self.msg_queues[msg.address]._skips += 1
                elif msg.address in self.async_msgs:
                    if sync:
                        self.sync(timeout=timeout, server_address=server_address)
            except (Empty, TimeoutError) as timeout_error:
                raise ChildProcessError(
                    f"Failed to sync after message to "
                    f"{'sclang' if sclang else 'scsynth'}"
                    f": {msg.address}") from timeout_error
        elif isinstance(content, osc_bundle.OscBundle):
            # logging
            if _LOGGER.isEnabledFor(logging.INFO):
                _LOGGER.info(
                    "send to %s : %s contents size %s ", receiver, content, len(content._contents))
        else:
            _LOGGER.info("send to %s : %s", receiver, content)

    def sync(self, timeout=5, server_address=None):
        """Sync with the scsynth server with the /sync command.

        Parameters
        ----------
        timeout : int, optional
            Time in seconds that will be waited for sync.
             (Default value = 5)

        """
        timeout_end = time.time() + timeout
        synced = False
        while not synced:
            sync_id = randint(1000, 9999)
            msg = build_message("/sync", sync_id)
            synced = (sync_id == self.send(msg, server_address=server_address))
            if time.time() >= timeout_end:
                raise TimeoutError(
                    'timeout while trying to sync with the server')
        return synced

    def msg(self, msg_addr, msg_args=None, sclang=False, sync=True, timeout=5):
        """Sends OSC message over UDP to either sclang or scsynth

        Parameters
        ----------
        msg_addr : str
            SuperCollider address
        msg_args : list, optional
            List of arguments to add to message.
             (Default value = None)
        sclang : bool, optional
            If True send message to sclang.
             (Default value = False)
        sync : bool, optional
            If True send message and wait for sync or response
            otherwise send the message and return directly.
             (Default value = True)
        timeout : int, optional
            timeout in seconds for sync and response.
             (Default value = 5)

        Returns
        -------
        obj
            response if sync was True and message is in `msg_pairs`

        """

        msg = build_message(msg_addr, msg_args)
        return self.send(msg, sclang=sclang, sync=sync, timeout=timeout)

    def bundle(self, timestamp, msg_addr=None, msg_args=None):
        """Generate a bundle builder.

        This allows the user to easly add messages/bundles and send it.

        Parameters
        ----------
        timestamp : int
            Time at which bundle content should be executed.
            If timestamp <= 1e6 it is added to time.time().
        msg_addr : str
            SuperCollider address.
        msg_args : list, optional
            List of arguments to add to message.
             (Default value = None)

        Returns
        -------
        OscBundleBuilder
            custom pythonosc BundleBuilder with add_msg and send
        """
        bundle = Bundler(timestamp, msg_addr, msg_args, server=self)
        return bundle

    def __del__(self):
        self.exit()

    def exit(self):
        """Shuts down the sc3nb server"""

        print("Shutting down osc communication...")
        self.server.shutdown()
        print("Done.")
