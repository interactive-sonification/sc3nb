"""Module with utlilty functions - especially for handling code snippets"""
import inspect
import re
from typing import Any

import numpy as np


def remove_comments(code: str) -> str:
    """Removes all c-style comments from code.

    This removes `//single-line` or `/* multi-line */`  comments.

    Parameters
    ----------
    code : str
        Code where comments should be removed.

    Returns
    -------
    str
        code string without comments
    """
    # function code by Onur Yildirim (https://stackoverflow.com/a/18381470)
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

    return regex.sub(_replacer, code)


def parse_pyvars(code: str, frame_nr: int = 2):
    """Looks through call stack and finds values of variables.

    Parameters
    ----------
    code : str
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
    matches = re.findall(r"\s*\^[A-Za-z_]\w*\s*", code)

    pyvars = {match.split("^")[1].strip(): None for match in matches}
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
        raise NameError("name(s) {} not defined".format(missing_vars))
    return pyvars


def replace_vars(code: str, pyvars: dict) -> str:
    """Replaces python variables with SuperCollider literals in code.

    This replaces the pyvars preceded with ^ in the code with a SC literal.
    The conversion is done with convert_to_sc.

    Parameters
    ----------
    code : str
        SuperCollider Code with python injections.
    pyvars : dict
        Dict with variable names and values.

    Returns
    -------
    str
        Code with injected variables.
    """
    for pyvar, value in pyvars.items():
        pyvar = "^" + pyvar
        value = convert_to_sc(value)
        code = code.replace(pyvar, value)
    return code


def convert_to_sc(obj: Any) -> str:
    """Converts python objects to SuperCollider code literals.

    This supports currently:

    * numpy.ndarray -> SC Array representation
    * complex type -> SC Complex
    * strings -> if starting with sc3: it will be used as SC code
                 if it starts with a \\ (single escaped backward slash) it will be used as symbol
                 else it will be inserted as string

    For unsupported types the __repr__ will be used.

    Parameters
    ----------
    obj : Any
        object that should be converted to a SuperCollider code literal.

    Returns
    -------
    str
        SuperCollider Code literal
    """
    if isinstance(obj, np.ndarray):
        return obj.tolist().__repr__()
    if isinstance(obj, complex):
        return "Complex({0}, {1})".format(obj.real, obj.imag)
    if isinstance(obj, str):
        if obj.startswith("sc3:"):  # start sequence for sc3-code
            return "{}".format(obj[4:])
        if obj.startswith(r"\\") and not obj.startswith(r"\\\\"):
            return "'{}'".format(obj[1:])  # 'x' will be interpreted as symbol
        if obj.startswith(r"\\\\"):
            obj = obj[1:]
        return '"{}"'.format(obj)  # "x" will be interpreted as string
    # further type conversion can be added in the future
    return obj.__repr__()
