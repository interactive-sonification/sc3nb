"""Collection of helper functions for the libary"""

import inspect
import os
import re
import sys

import numpy as np

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


def parse_pyvars(cmdstr, frame_nr=2):
    """Parses through call stack and finds
    value of string representations of variables

    Parameters
    ----------
    cmdstr : string
        SuperCollider command to be parsed
    frame_nr : int, optional
        on which frame to start, by default 2 (grandparent frame)

    Returns
    -------
    dict
        {variable_name: variable_value}

    Raises
    ------
    NameError
        If the variable value could not be found.
    """
    matches = re.findall(r'\s*\^[A-Za-z_]\w*\s*', cmdstr)

    pyvars = {match.split('^')[1].strip(): None for match in matches}
    missing_vars = list(pyvars.keys())

    stack = inspect.stack()
    frame = None
    try:
        while missing_vars and frame_nr < len(stack):
            frame = stack[frame_nr][0]
            for pyvar in pyvars:
                if pyvar not in missing_vars:
                    continue
                # check for variable in local variables
                if pyvar in frame.f_locals:
                    pyvars[pyvar] = frame.f_locals[pyvar]
                    missing_vars.remove(pyvar)
                # check for variable in global variables
                elif pyvar in frame.f_globals:
                    pyvars[pyvar] = frame.f_globals[pyvar]
                    missing_vars.remove(pyvar)
            frame_nr += 1
    finally:
        del frame
        del stack
    if missing_vars:
        raise NameError('name(s) {} not defined'.format(missing_vars))
    return pyvars


def replace_vars(cmdstr, pyvars):
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
        if obj.startswith("sc3:"):  # start sequence for sc3-code
            return "{}".format(obj[4:])
        if obj.startswith(r"\\") and not obj.startswith(r"\\\\"):
            return "'{}'".format(obj[1:])  # 'x' will be interpreted as symbol
        else:
            if obj.startswith(r"\\\\"):
                obj = obj[1:]
            return '"{}"'.format(obj)  # "x" will be interpreted as string
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
