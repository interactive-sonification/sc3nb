'''Module for parsing the OSC packets from sclang.

This implements a extension of the OSC protocol.
A bundle is now allowed to consist of other bundles or
lists.

OSC List consists of the following bytes:
    4 bytes (int) : list_size
    n bytes (string) : OSC type tag
    n bytes (x) : content as specified by type tag

This extension is needed as sclang is sending Arrays
as this list or when nested as bundles with inner list

'''
import logging
import math

from pythonosc.osc_bundle import OscBundle
from pythonosc.parsing import osc_types

TYPE_TAG_MARKER = ord(b',')
TYPE_TAG_INDEX = 4
NUM_SIZE = 4
INT_TAG = ord(b'i')
BYTES_2_TYPE = {
    'i': osc_types.get_int,
    'f': osc_types.get_float,
    'd': osc_types.get_double,
    's': osc_types.get_string,
    'N': lambda dgram, start_index: (None, start_index),
    'I': lambda dgram, start_index: (float('inf'), start_index),
    'T': lambda dgram, start_index: (True, start_index),
    'F': lambda dgram, start_index: (False, start_index)
}


class ParseError(Exception):
    '''Base exception for when a datagram parsing error occurs.'''


def _get_aligned_index(index):
    '''Get next multiple of NUM_SIZE from index'''
    return NUM_SIZE * int(math.ceil((index)/NUM_SIZE))


def _parse_list(dgram, start_index):
    '''List consists of the following bytes:
    4 bytes (int) : list_size
    n bytes (string) : OSC type tag
    n bytes (x) : content as specified by type tag
    '''
    # parse list size
    logging.debug("[ start parsing list: %s", dgram[start_index:])
    list_size, start_index = osc_types.get_int(dgram, start_index)

    # parse type tag
    type_tag, start_index = osc_types.get_string(dgram, start_index)
    if type_tag.startswith(','):
        type_tag = type_tag[1:]

    logging.debug("list with size %d and content '%s'", list_size, type_tag)

    # parse content
    value_list = []
    for tag in type_tag:
        try:
            value, start_index = BYTES_2_TYPE[tag](dgram, start_index)
        except KeyError:
            raise ParseError('type tag "{}" not understood'.format(chr(tag)))
        logging.debug("new value %s", value)
        value_list.append(value)

    logging.debug("resulting list %s", value_list)
    logging.debug("] end parsing list")
    return value_list, start_index


def _parse_osc_bundle_element(dgram, start_index):
    '''Parse an element from a osc bundle.

    The element needs to be either a osc bundle or a list
    '''
    elem_size, start_index = osc_types.get_int(dgram, start_index)
    logging.debug(">> parse osc bundle element (size: %d): %s ",
                  elem_size, dgram[start_index:start_index+elem_size])

    if OscBundle.dgram_is_bundle(dgram[start_index:start_index+elem_size]):
        logging.debug("found bundle")
        msgs, start_index = _parse_bundle(dgram, start_index)
        return msgs, start_index

    if dgram[start_index+TYPE_TAG_INDEX] == TYPE_TAG_MARKER:
        logging.debug("found list")
        value_list, start_index = _parse_list(dgram, start_index)
        return value_list, start_index

    raise ParseError("Datagram not recognized")


BYTES_2_TYPE['b'] = _parse_osc_bundle_element


def _parse_bundle(dgram, start_index):
    '''Parsing bundle'''
    logging.debug("## start parsing bundle: %s", dgram[start_index:])

    if dgram[start_index:start_index+8] != b'#bundle\x00':
        raise ParseError(
            "Datagram of bundles should start with b'#bundle\x00'")
    start_index += 8

    timetag, start_index = osc_types.get_ttag(dgram, start_index)
    logging.debug("bundle timetag: %s", timetag)

    msgs = []
    while start_index < len(dgram):
        sc_msg, start_index = _parse_osc_bundle_element(dgram, start_index)
        msgs.append(sc_msg)

    start_index = _get_aligned_index(start_index)
    logging.debug("parsed bytes %s", dgram[:start_index])
    logging.debug("msgs %s", msgs)
    logging.debug("## end parsing bundle ")
    return msgs, start_index


def parse_sclang_osc_packet(data):
    '''Parses the OSC packet from sclang.'''
    try:
        if len(data) > TYPE_TAG_INDEX + 1:
            if data[TYPE_TAG_INDEX] == TYPE_TAG_MARKER:
                return _parse_list(data, 0)[0]
            elif data[:8] == b'#bundle\x00':
                return _parse_bundle(data, 0)[0]
    except ParseError as error:
        logging.warning('Ignoring ParseError:\n%s\nreturning blob', error)
    return data
