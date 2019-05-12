"""Collection of helper functions for the libary"""

import inspect
import logging
import numbers
import os
import re
import sys

import numpy as np
from pythonosc.parsing import osc_types


def parse_sclang_blob(data):
    '''Parses the blob from a SuperCollider osc message'''

    TYPE_TAG_MARKER = ord(b',')
    TYPE_TAG_START = 4
    NUM_SIZE = 4
    INT_TAG = ord(b'i')
    bytes2type = {
        ord(b'i'): lambda data: osc_types.get_int(data, 0),
        ord(b'f'): lambda data: osc_types.get_float(data, 0),
        ord(b's'): lambda data: osc_types.get_string(data, 0),
        ord(b'N'): lambda data: (None, 0),
        ord(b'I'): lambda data: (np.inf, 0),
        ord(b'T'): lambda data: (True, 0),
        ord(b'F'): lambda data: (False, 0)
    }

    def _get_aligned_pos(pos):
        return NUM_SIZE * int(np.ceil((pos)/NUM_SIZE))

    def _parse_list(data):
        logging.debug("[ start parsing list: {}".format(data))
        list_size, _ = bytes2type[INT_TAG](data)
        type_tag_offset = _get_aligned_pos(list_size + 2)
        type_tag_end = TYPE_TAG_START + type_tag_offset
        type_tag = data[TYPE_TAG_START + 1: TYPE_TAG_START + 1 + list_size]
        value_list = []
        idx = type_tag_end
        for t in type_tag:
            try:
                value, num_bytes = bytes2type[t](data[idx:])
            except KeyError:
                raise Exception('type tag "{}" not understood'.format(chr(t)))
            logging.debug("new value {}".format(value))
            value_list.append(value)
            idx += num_bytes

        logging.debug("resulting list {}".format(value_list))
        logging.debug("] end parsing list")
        return value_list, idx

    def _parse_sc_msg(data):
        logging.debug(">> parse sc msg: {}".format(data))
        msg_size, _ = bytes2type[INT_TAG](data)
        logging.debug("msg size {}".format(msg_size))
        data = data[NUM_SIZE:]

        if data[:8] == b'#bundle\x00':
            logging.debug("found bundle")
            msgs, bundle_size = _parse_bundle(data)
            return msgs, bundle_size + NUM_SIZE
        elif data[TYPE_TAG_START] == TYPE_TAG_MARKER:
            logging.debug("found list")
            value_list, list_size = _parse_list(data[:msg_size])
            return value_list, list_size + NUM_SIZE
        else:
            raise Exception("Datagram not recognized")

    bytes2type[ord(b'b')] = _parse_sc_msg

    def _parse_bundle(data):
        logging.debug("## start parsing bundle: {}".format(data))
        msgs = []
        msg_count = ord(data[8+3:8+4]) - ord("\x80")
        bundle_size = 16  # skip header
        logging.debug("msg count {}".format(msg_count))
        while msg_count > 0:
            sc_msg, msg_size = _parse_sc_msg(data[bundle_size:])
            msgs.append(sc_msg)
            bundle_size += msg_size
            msg_count -= 1
            logging.debug("msgs left {}".format(msg_count))

        bundle_size = _get_aligned_pos(bundle_size)
        logging.debug("parsed bytes {}".format(data[:bundle_size]))
        logging.debug("msgs {}".format(msgs))
        logging.debug("## end parsing bundle ")
        return msgs, bundle_size

    try:
        if len(data) > TYPE_TAG_START + 1:
            if data[TYPE_TAG_START] == TYPE_TAG_MARKER:
                return _parse_list(data)[0]
            elif data[:8] == b'#bundle\x00':
                return _parse_bundle(data)[0]
    except Exception as e:
        logging.warning('Ignoring Exception:\n{}\nreturning blob'.format(e))
    return data


def remove_comments(string):
    """Removes all //single-line or /* multi-line */ c-style comments

    Arguments:
        string {str} -- Code

    Returns:
        str -- Code without comments
    """

    # function code by Onur Yildirim
    # first group captures quoted strings (double or single)
    # second group captures comments (//single-line or /* multi-line */)
    # alternative cares for escaped quotes
    # pattern = r"(\".*?(?<!\\)\"|\'.*?(?<!\\)\')|(/\*.*?\*/|//[^\r\n]*$)"
    pattern = r"(\".*?\"|\'.*?\')|(/\*.*?\*/|//[^\r\n]*$)"
    regex = re.compile(pattern, re.MULTILINE | re.DOTALL)

    def _replacer(match):
        # if the 2nd group (capturing comments) is not None,
        # it means we have captured a non-quoted (real) comment string.
        if match.group(2) is not None:
            return ""  # so we will return empty to remove the comment
        else:  # otherwise, we will return the 1st group
            return match.group(1)  # captured quoted-string
    return regex.sub(_replacer, string)


def parse_pyvars(cmdstr):
    '''Parses through call stack and finds
    value of string representations of variables
    '''
    matches = re.findall(r'\s*\^[A-Za-z_]\w*\s*', cmdstr)

    pyvars = {match.split('^')[1].strip(): None for match in matches}

    # get frame from grandparent call stack
    frame = inspect.stack()[2][0]

    for pyvar in pyvars:
        # check for variable in local variables
        if pyvar in frame.f_locals:
            pyvars[pyvar] = frame.f_locals[pyvar]
        # check for variable in global variables
        elif pyvar in frame.f_globals:
            pyvars[pyvar] = frame.f_globals[pyvar]
        else:
            raise NameError('name \'{}\' is not defined'.format(pyvar))

    return pyvars


def replace_vars(cmdstr, pyvars):
    if pyvars is None:
        pyvars = parse_pyvars(cmdstr)

    '''Replaces python variables with sc string representation'''
    for pyvar, value in pyvars.items():
        pyvar = '^' + pyvar
        value = convert_to_sc(value)
        cmdstr = cmdstr.replace(pyvar, value)
    return cmdstr


def convert_to_sc(obj):
    '''Converts python objects to SuperCollider code literals
    representations
    '''
    if isinstance(obj, np.ndarray):
        return obj.tolist().__repr__()
    if isinstance(obj, complex):
        return 'Complex({0}, {1})'.format(obj.real, obj.imag)
    if isinstance(obj, str):
        return '"{0}"'.format(obj)
    # further type conversion can be added in the future
    return obj.__repr__()


def find_executable(executable, path=''):
    """Looks for executable in os $PATH or specified path

    Arguments:
        executable {str} -- Executable to be found

    Keyword Arguments:
        path {str} -- Path at which to look for
                      executable (default: {''})

    Raises:
        FileNotFoundError -- Raised if executable
                             cannot be found

    Returns:
        str -- Full path to executable
    """

    if not path:
        path = os.environ['PATH']
    paths = path.split(os.pathsep)
    extlist = ['']
    if os.name == 'os2':
        _, ext = os.path.splitext(executable)
        # executable files on OS/2 can have an arbitrary extension, but
        # .exe is automatically appended if no dot is present in the name
        if not ext:
            executable = executable + ".exe"
    elif sys.platform == 'win32':
        pathext = os.environ['PATHEXT'].lower().split(os.pathsep)
        _, ext = os.path.splitext(executable)
        if ext.lower() not in pathext:
            extlist = pathext
    for ext in extlist:
        execname = executable + ext
        if os.path.isfile(execname):
            return execname
        for path in paths:
            file = os.path.join(path, execname)
            if os.path.isfile(file):
                return file
    raise FileNotFoundError("Unable to find sclang executable")
