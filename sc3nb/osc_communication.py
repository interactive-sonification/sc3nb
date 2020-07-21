"""OSC communication

Classes and functions to communicate with the OSC protocol with
SuperCollider over UDP
"""

import errno
import logging
import select
import socket
import threading
import time
from queue import Empty, Queue

from random import randint
from pythonosc import (dispatcher, osc_bundle_builder, osc_message,
                       osc_message_builder, osc_server)

from .tools import parse_sclang_blob

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


def _add_msg(self, msg_addr, msg_args):
    """Add a pythonsosc OSC message to this bundle.

    Parameters
    ----------
    msg_addr : str
        SuperCollider address.
    msg_args : list
        List of arguments to add to message.

    Returns
    -------
    self
        for call chaining
    """
    msg = build_message(msg_addr, msg_args)
    self.add_content(msg)
    return self


osc_bundle_builder.OscBundleBuilder.add_msg = _add_msg


def _send(self, sclang=False):
    """Build and send this bundle.

    Parameters
    ----------
    sclang : bool
            If True sends msg to sclang else sends msg to scsynth.
    """
    self.osc.send(self.build(), sclang)


osc_bundle_builder.OscBundleBuilder.send = _send


def build_bundle(timetag, msg_addr, msg_args):
    """Builds pythonsosc OSC bundle

    Parameters
    ----------
    timetag : int
        Time at which bundle content should be executed.
        If timetag < 1e6 it is added to time.time().
    msg_addr : str
        SuperCollider address.
    msg_args : list
        List of arguments to add to message.

    Returns
    -------
    OscBundle
        Bundle ready to be sent.

    """

    if msg_args is None:
        msg_args = []

    if timetag < 1e6:
        timetag = time.time() + timetag
    bundle = osc_bundle_builder.OscBundleBuilder(timetag)
    msg = build_message(msg_addr, msg_args)
    bundle.add_content(msg)
    bundle = bundle.build()
    return bundle


def build_message(msg_addr, msg_args):
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

    if not msg_addr.startswith('/'):
        msg_addr = '/' + msg_addr

    builder = osc_message_builder.OscMessageBuilder(address=msg_addr)
    if not hasattr(msg_args, '__iter__') or isinstance(msg_args, (str, bytes)):
        msg_args = [msg_args]
    for msg_arg in msg_args:
        builder.add_arg(msg_arg)
    msg = builder.build()
    return msg


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

    def __put(self, address, *args):
        if self.process:
            args = self.process(args)
        else:
            if len(args) == 1:
                args = args[0]
            elif len(args) == 0:
                args = None
        self.queue.put(args)

    @property
    def skips(self):
        """Counts how many times this queue was not synced"""
        return self._skips

    @property
    def _map_values(self):
        return self.address, self.__put

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
                logging.warn(f"AddressQueue: skipped value {skipped_value}")
                self._skips -= 1
        if self._skips > 0:
            self._skips -= 1
        val = self.queue.get(block=True, timeout=timeout)
        self.queue.task_done()
        return val

    def show(self):
        """Print the content of the queue."""
        print(list(self.queue.queue))

    def __repr__(self):
        return f"AddressQueue {self.address} : {list(self.queue.queue)}"


def preprocess_return(value):
    """Preprocessing function for /return values

    Parameters
    ----------
    value : tuple
        tuple with one entry that is the send data

    Returns
    -------
    obj
        data

    """
    if len(value) == 1:
        value = value[0]
        if type(value) == bytes:
            value = parse_sclang_blob(value)
    return value


class OscCommunication():
    """Class to send and receive OSC messages and bundles."""

    def __init__(self, server_ip='127.0.0.1', server_port=OSCCOM_DEFAULT_PORT,
                 sclang_ip='127.0.0.1', sclang_port=SCLANG_DEFAULT_PORT,
                 scsynth_ip='127.0.0.1', scsynth_port=SCSYNTH_DEFAULT_PORT):
        print("Starting osc communication...")

        # set SuperCollider addresses
        self.set_sclang(sclang_ip, sclang_port)
        self.set_scsynth(scsynth_ip, scsynth_port)

        # start server
        server_dispatcher = dispatcher.Dispatcher()
        while True:
            try:
                self.server = osc_server.ThreadingOSCUDPServer(
                    (server_ip, server_port), server_dispatcher)
                print("This sc3nb sc instance is at port: {}"
                      .format(server_port))
                break
            except OSError as e:
                if e.errno == errno.EADDRINUSE:
                    server_port += 1

        # set known messages
        self.async_msgs = ASYNC_MSGS
        self.msg_pairs = MSG_PAIRS

        # init queues for msg pairs
        self.msg_queues = {}
        self.update_msg_queues()

        # init special msg queues
        self.returns = AddressQueue("/return", preprocess_return)
        server_dispatcher.map(*self.returns._map_values)

        # As /done messages have no purpose for us at this point
        # we don't collect /done messages
        # self.dones = AddressQueue("/done")
        # server_dispatcher.map(*self.dones._map_values)

        # set logging handlers
        server_dispatcher.map("/fail", self.__warn, needs_reply_address=True)
        server_dispatcher.map("/*", self.__log, needs_reply_address=True)

        self.server_thread = threading.Thread(
            target=self.server.serve_forever)
        self.server_thread.start()

        print("Done.")

    def update_msg_queues(self, new_msg_pairs=None):
        """Update the queues used for message receiving.

        This method will check for all `msg_pairs` if there is a AddressQueue
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
                self.server.dispatcher.map(*addr_queue._map_values)
                self.msg_queues[msg_addr] = addr_queue

    def __check_sender(self, sender):
        if sender == self.sclang_address:
            sender = "sclang"
        elif sender == self.scsynth_address:
            sender = "scsynth"
        return sender

    def __log(self, sender, *args):
        logging.info("OSC_COM: osc msg received from {}: {:.55}"
                     .format(self.__check_sender(sender), str(args)))

    def __warn(self, sender, *args):
        logging.warn("OSC_COM: Error from {}:\n {}"
                     .format(self.__check_sender(sender), args))

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

    def send(self, content, sclang=False):
        """Sends OSC message or bundle to sclang or scsnyth

        Parameters
        ----------
        content : OscMessage or OscBundle
            Object with `dgram` attribute.
        sclang : bool
            If True sends msg to sclang else sends msg to scsynth.

        """

        logging.debug(f"OSC_COM: sending dgram:\n{content.dgram}")
        if sclang:
            self.server.socket.sendto(content.dgram, (self.sclang_address))
        else:
            self.server.socket.sendto(content.dgram, (self.scsynth_address))

    def sync(self, timeout=5):
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
            synced = sync_id == self.msg("/sync", sync_id)
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
            timeout for sync and response.
             (Default value = 5)

        Returns
        -------
        obj
            response if sync was True and message is in `msg_pairs`

        """

        msg = build_message(msg_addr, msg_args)
        self.send(msg, sclang)
        logging.info("OSC_COM: send {} {:.55}".format(
            msg.address,
            str(msg.params)))
        logging.debug("OSC_COM: msg.params {}".format(msg.params))
        try:
            if msg.address in self.msg_pairs:
                if sync:
                    return self.msg_queues[msg.address].get(timeout, skip=True)
                else:
                    self.msg_queues[msg.address]._skips += 1
            elif msg.address in self.async_msgs:
                if sync:
                    self.sync(timeout=timeout)
        except (Empty, TimeoutError):
            raise ChildProcessError(
                f"Failed to sync after message to "
                f"{'sclang' if sclang else 'scsynth'}"
                f": {msg.address} {str(msg.params):.55}")

    def bundle(self, timetag, msg_addr, msg_args=None, sclang=False):
        """Sends OSC bundle over UDP to either sclang or scsynth

        Parameters
        ----------
        timetag : int
            Time at which bundle content should be executed.
            If timetag < 1e6 it is added to time.time().
        msg_addr : str
            SuperCollider address.
        msg_args : list, optional
            List of arguments to add to message.
             (Default value = None)
        sclang : bool, optional
            If True send message to sclang.
             (Default value = False)

        """

        bundle = build_bundle(timetag, msg_addr, msg_args)
        self.send(bundle, sclang)

    def bundle_builder(self, timetag):
        """Generate a bundle builder.

        This allows the user to easly add messages and send it.

        Parameters
        ----------
        timetag : int
            Time at which bundle content should be executed.
            If timetag < 1e6 it is added to time.time().

        Returns
        -------
        OscBundleBuilder
            custom pythonosc BundleBuilder with add_msg and send
        """
        if timetag < 1e6:
            timetag = time.time() + timetag
        bundle_builder = osc_bundle_builder.OscBundleBuilder(timetag)
        bundle_builder.osc = self
        return bundle_builder

    def exit(self):
        """Shuts down the sc3nb server"""

        self.server.shutdown()
