"""Classes and functions to communicate with SuperCollider via
OSC messages over UDP
"""

import select
import socket
import time
import logging

from pythonosc import osc_bundle_builder, osc_message, osc_message_builder


def build_bundle(timetag, msg_addr, msg_args):
    """Builds pythonsosc OSC bundle

    Arguments:
            timetag {int} -- Time at which bundle content
                             should be executed, either
                             in absolute or relative time
            msg_addr {str} -- SuperCollider address
                              E.g. '/s_new'
            msg_args {list} -- List of arguments to add
                               to message

    Returns:
        OscBundle -- Bundle ready to be sent
    """

    if timetag < 1e6:
        timetag = time.time() + timetag
    bundle = osc_bundle_builder.OscBundleBuilder(timetag)
    msg = build_message(msg_addr, msg_args)
    bundle.add_content(msg)
    bundle = bundle.build()
    return bundle


def build_message(msg_addr, msg_args):
    """Builds pythonsosc OSC message

    Arguments:
            msg_addr {str} -- SuperCollider address
                              E.g. '/s_new'
            msg_args {list} -- List of arguments to add
                               to message

    Returns:
        OscMessage -- Message ready to be sent
    """

    builder = osc_message_builder.OscMessageBuilder(address=msg_addr)
    if not hasattr(msg_args, '__iter__') or isinstance(msg_args, (str, bytes)):
        msg_args = [msg_args]
    for msg_arg in msg_args:
        builder.add_arg(msg_arg)
    msg = builder.build()
    return msg


class UDPClient():
    """Class to send and receive messages OSC messages via UDP
    from and to sclang and scsynth
    """

    def __init__(self):
        self._sclang_addr = '127.0.0.1'
        self._sclang_port = 57120
        self._server_addr = '127.0.0.1'
        self._server_port = 57110

        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.setblocking(0)
        self._sock.bind(('', 0))

        self.client_addr, self.client_port = self._sock.getsockname()

        if self.client_addr == '0.0.0.0':
            self.client_addr = '127.0.0.1'

    def send(self, msg, sclang):
        """Sends OSC message or bundle to sclang or scsnyth

        Arguments:
            msg {OscMessage|OscBundle} -- Message or bundle
                                          to be sent
            sclang {bool} -- if True sends msg to sclang
                             else sends msg to scsynth
        """

        if sclang:
            self._sock.sendto(
                msg.dgram, (self._sclang_addr, self._sclang_port))
        else:
            self._sock.sendto(
                msg.dgram, (self._server_addr, self._server_port))

    def set_server(self, server_addr, server_port):
        '''Set address and port of scsynth server'''
        self._server_addr = server_addr
        self._server_port = server_port

    def set_sclang(self, sclang_addr, sclang_port):
        '''Set address and port of sclang'''
        self._sclang_addr = sclang_addr
        self._sclang_port = sclang_port

    def recv(self, dgram_size=1024, timeout=1):
        '''Receive UDP OSC message from SC'''
        ready = select.select([self._sock], [], [], timeout)[0]
        if ready:
            dgram = self._sock.recv(dgram_size)
            logging.debug("dgram received {}".format(dgram))
            if dgram[:8] == b'/return\x00':
                msg = osc_message.OscMessage(dgram)
                logging.debug("msg.params {}".format(msg.params))
                if len(msg.params) == 0:
                    return None
                return msg.params[0]
            else:
                return self.recv(dgram_size, timeout)
        raise TimeoutError('socket timeout when receiving data from SC')

    def exit(self):
        '''Close socket'''
        self._sock.close()
