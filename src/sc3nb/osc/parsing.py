"""Module for parsing OSC packets from sclang.

This implements an extension of the OSC protocol.
A bundle is now allowed to consist of other bundles or
lists.

This extension is needed as sclang is sending Arrays
as this list or when nested as bundles with inner list

"""
import logging
import math
from typing import Any, Sequence, Tuple, Union

from pythonosc.osc_bundle import OscBundle
from pythonosc.parsing import osc_types

_LOGGER = logging.getLogger(__name__)


SYNTH_DEF_MARKER = b"SCgf"
TYPE_TAG_MARKER = ord(b",")
TYPE_TAG_INDEX = 4
NUM_SIZE = 4
BYTES_2_TYPE = {
    "i": osc_types.get_int,
    "f": osc_types.get_float,
    "d": osc_types.get_double,
    "s": osc_types.get_string,
    "N": lambda dgram, start_index: (None, start_index),
    "I": lambda dgram, start_index: (float("inf"), start_index),
    "T": lambda dgram, start_index: (True, start_index),
    "F": lambda dgram, start_index: (False, start_index),
}


class ParseError(Exception):
    """Base exception for when a datagram parsing error occurs."""


def _get_aligned_index(index: int) -> int:
    """Get next multiple of NUM_SIZE from index

    Parameters
    ----------
    index : int
        starting index

    Returns
    -------
    int
        next multiple of NUM_SIZE from index
    """
    return NUM_SIZE * math.ceil(index / NUM_SIZE)


def _parse_list(dgram: bytes, start_index: int) -> Tuple[Sequence[Any], int]:
    """Parse a OSC List

    List consists of the following bytes:
    4 bytes (int) : list_size
    n bytes (string) : OSC type tag
    n bytes (x) : content as specified by type tag

    Parameters
    ----------
    dgram : bytes
        datagram with the list
    start_index : int
        parsing starting index

    Returns
    -------
    Tuple[Sequence[Any], int]
        parsed list contents, starting index + number of consumed bytes

    Raises
    ------
    ParseError
        If datagram is invalid.
    """
    # parse list size
    _LOGGER.debug("[ start parsing list: %s", dgram[start_index:])
    list_size, start_index = osc_types.get_int(dgram, start_index)

    # parse type tag
    type_tag, start_index = osc_types.get_string(dgram, start_index)
    if type_tag.startswith(","):
        type_tag = type_tag[1:]

    _LOGGER.debug("list with size %d and content '%s'", list_size, type_tag)

    # parse content
    value_list = []
    for tag in type_tag:
        try:
            value, start_index = BYTES_2_TYPE[tag](dgram, start_index)
        except KeyError:
            raise ParseError('type tag "{}" not understood'.format(chr(tag)))
        _LOGGER.debug("new value %s", value)
        value_list.append(value)

    _LOGGER.debug("resulting list %s", value_list)
    _LOGGER.debug("] end parsing list")
    return value_list, start_index


def _parse_osc_bundle_element(
    dgram: bytes, start_index: int
) -> Tuple[Union[Sequence[Any], bytes], int]:
    """Parse an element from an OSC bundle.

    The element needs to be either an OSC bundle or a list

    Parameters
    ----------
    dgram : bytes
        datagram with the bundle element
    start_index : int
        parsing starting index

    Returns
    -------
    Tuple[Union[Sequence[Any], bytes], int]
        parsed content of the bundle element, starting index + number of consumed bytes

    Raises
    ------
    ParseError
        If the datagram is invalid.
    """
    elem_size, start_index = osc_types.get_int(dgram, start_index)
    _LOGGER.debug(
        ">> parse OSC bundle element (size: %d): %s ",
        elem_size,
        dgram[start_index : start_index + elem_size],
    )

    if OscBundle.dgram_is_bundle(dgram[start_index : start_index + elem_size]):
        _LOGGER.debug("found bundle")
        msgs, start_index = _parse_bundle(dgram, start_index)
        return msgs, start_index

    if dgram[start_index + TYPE_TAG_INDEX] == TYPE_TAG_MARKER:
        _LOGGER.debug("found list")
        value_list, start_index = _parse_list(dgram, start_index)
        return value_list, start_index

    if dgram[start_index : start_index + 4] == SYNTH_DEF_MARKER:
        _LOGGER.debug("found SynthDef blob")
        synth_def = dgram[start_index : start_index + elem_size]
        start_index = start_index + elem_size
        return synth_def, start_index

    raise ParseError("Datagram not recognized")


BYTES_2_TYPE["b"] = _parse_osc_bundle_element


def _parse_bundle(dgram: bytes, start_index: int) -> Tuple[Sequence[Any], int]:
    """Parsing bundle

    Parameters
    ----------
    dgram : bytes
        datagram with the bundle
    start_index : int
        parsing starting index

    Returns
    -------
    tuple[Sequence[Any], int]
        parsed content, starting index + number of consumed bytes

    Raises
    ------
    ParseError
        If the datagram is invalid
    """
    _LOGGER.debug("## start parsing bundle: %s", dgram[start_index:])

    if dgram[start_index : start_index + 8] != b"#bundle\x00":
        raise ParseError("Datagram of bundles should start with b'#bundle\x00'")
    start_index += 8

    timetag, start_index = osc_types.get_timetag(dgram, start_index)
    _LOGGER.debug("bundle timetag: %s", timetag)

    msgs = []
    while start_index < len(dgram):
        sc_msg, start_index = _parse_osc_bundle_element(dgram, start_index)
        msgs.append(sc_msg)

    start_index = _get_aligned_index(start_index)
    _LOGGER.debug("parsed bytes %s", dgram[:start_index])
    _LOGGER.debug("msgs %s", msgs)
    _LOGGER.debug("## end parsing bundle ")
    return msgs, start_index


def parse_sclang_osc_packet(data: bytes) -> Union[bytes, Sequence[Any]]:
    """Parses the OSC packet from sclang.

    Parameters
    ----------
    data : bytes
        bytes sent by sclang

    Returns
    -------
    bytes or Sequence[Any]
        unchanged bytes or content of bundles/messages
    """
    try:
        if len(data) > TYPE_TAG_INDEX + 1:
            if data[TYPE_TAG_INDEX] == TYPE_TAG_MARKER:
                return _parse_list(data, 0)[0]
            elif data[:8] == b"#bundle\x00":
                return _parse_bundle(data, 0)[0]
    except ParseError as error:
        _LOGGER.warning("Ignoring ParseError:\n%s\nreturning blob", error)
    return data


def preprocess_return(value: Sequence[Any]) -> Sequence[Any]:
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
