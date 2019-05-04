"""Collection of helper functions for the libary"""

import inspect
import numbers
import os
import re
import sys

import numpy as np
from pythonosc.parsing import osc_types


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
    }

    def __get_aligned_pos(pos):
        return NUM_SIZE * int(np.ceil((pos)/NUM_SIZE))

    def __parse_list(data):
        list_size, _ = bytes2type[INT_TAG](data)
        type_tag_offset = __get_aligned_pos(list_size + 2)
        type_tag_end = TYPE_TAG_START + type_tag_offset
        type_tag = data[TYPE_TAG_START + 1: TYPE_TAG_START + 1 + list_size]
        value_list = []
        idx = type_tag_end
        for t in type_tag:
            value, num_bytes = bytes2type[t](data[idx:])
            value_list.append(value)
            idx += num_bytes

        return value_list, list_size

    def __parse_sc_msg(data):
        list_size, _ = bytes2type[INT_TAG](data)
        msg_size = __get_aligned_pos(NUM_SIZE + list_size)
        sc_list, _ = __parse_list(data[NUM_SIZE: msg_size])
        return sc_list, msg_size

    bytes2type[ord(b'b')] = __parse_sc_msg

    def __parse_bundle(data):
        bundle_size = len(data)
        lists = []
        idx = 16  # skip header
        while idx < bundle_size:
            sc_list, list_size = __parse_sc_msg(data[idx:])
            lists.append(sc_list)
            idx += list_size

        return lists, bundle_size

    if data[TYPE_TAG_START] == TYPE_TAG_MARKER:
        return __parse_list(data)[0]
    elif data[:8] == b'#bundle\x00':
        return __parse_bundle(data)[0]
    else:
        return data


def parse_pyvars(cmdstr):
    '''Parses through call stack and finds
    value of string representations of variables
    '''
    matches = re.findall(r'\s*\^[A-Za-z_]\w*\s*', cmdstr)

    pyvar_strs = [match[1:].strip() for match in matches]

    # get frame from grandparent call stack
    frame = inspect.stack()[2][0]
    # grab local variables
    local = frame.f_locals
    pyvars = {}
    # check for variable in local variables
    for pyvar_str in pyvar_strs:
        if pyvar_str in local:
            pyvars[pyvar_str] = local[pyvar_str]
    # if found in local variables, remove from search
    for pyvar in pyvars:
        if pyvar in pyvar_strs:
            pyvar_strs.remove(pyvar)
    # check for variable in global variables
    for pyvar_str in pyvar_strs:
        if pyvar_str in local:
            pyvars[pyvar_str] = local[pyvar_str]
    # if found in global variables, remove from search
    for pyvar in pyvars:
        if pyvar in pyvar_strs:
            pyvar_strs.remove(pyvar)
    # if any variables not found raise NameError
    for pyvar_str in pyvar_strs:
        raise NameError('name \'{}\' is not defined'.format(pyvar_str))
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
        return obj.tolist()
    if isinstance(obj, complex):
        return 'Complex({0}, {1})'.format(obj.real, obj.imag)
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
