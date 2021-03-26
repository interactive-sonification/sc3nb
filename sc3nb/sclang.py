"""Module for handling a SuperCollider language (sclang) process."""
import re
import sys
import inspect
import time
import warnings
import logging

from typing import NamedTuple, Any, Optional, Sequence, Tuple
from queue import Empty

import numpy as np

import sc3nb.resources as resources
from sc3nb.sc_objects.server import SCServer, ReplyAddress
from sc3nb.process_handling import Process, ProcessTimeout, ALLOWED_PARENTS

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())

SCLANG_DEFAULT_PORT = 57120
SC3NB_SCLANG_CLIENT_ID = 0

ANSI_ESCAPE = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')


class SynthArgument(NamedTuple):
    """Synth Argument rate and default value"""
    name: str
    rate: str
    default: Any


def remove_comments(code: str) -> str:
    """Removes all c-style comments from code.

    This removes //single-line or /* multi-line */  comments.

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
    matches = re.findall(r'\s*\^[A-Za-z_]\w*\s*', code)

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
        pyvar = '^' + pyvar
        value = convert_to_sc(value)
        code = code.replace(pyvar, value)
    return code


def convert_to_sc(obj: Any) -> str:
    """Converts python objects to SuperCollider code literals.

    This supports currently:
    numpy.ndarray -> SC Array representation
    complex type -> SC Complex
    strings -> if starting with sc3: it will be used as SC code
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


class SCLangError(Exception):
    """Exception for Errors related to SuperColliders sclang."""
    def __init__(self, message, sclang_output=None):
        super().__init__(message)
        self.sclang_output = sclang_output

class SCLang:
    """Class to control the SuperCollider Language Interpreter (sclang)."""

    def __init__(self) -> None:
        """Creates a python representation of sclang.

        Raises
        ------
        NotImplementedError
            When an unsupported OS was found.
        """
        self.process: Process
        self._server: Optional[SCServer] = None
        self.started: bool = False
        self._port: int = SCLANG_DEFAULT_PORT
        if sys.platform == "linux" or sys.platform == "linux2":
            self.prompt_str = 'sc3>'
        elif sys.platform == "darwin":
            self.prompt_str = 'sc3>'
        elif sys.platform == "win32":
            self.prompt_str = '->'
        else:
            raise NotImplementedError('Unsupported OS {}'.format(sys.platform))

    def start(self,
              sclang_path: Optional[str] = None,
              console_logging: bool = True,
              allowed_parents: Sequence[str] = ALLOWED_PARENTS) -> None:
        """Start and initilize the sclang process.

        This will also kill sclang processes that does not have allowed parents.

        Parameters
        ----------
        sclang_path : Optional[str], optional
            Path with the sclang executable, by default None
        console_logging : bool, optional
            If True log sclang output to console, by default True
        allowed_parents : Sequence[str], optional
            parents name of processes to keep, by default ALLOWED_PARENTS

        Raises
        ------
        SCLangError
            When starting or initilizing sclang failed.
        """
        if self.started:
            warnings.warn("sclang arlready started")
            return
        print('Starting sclang process...')
        self.process = Process(executable='sclang',
                               exec_path=sclang_path,
                               console_logging=console_logging,
                               allowed_parents=allowed_parents)
        try:
            self.read(expect='Welcome to SuperCollider', timeout=10)
        except ProcessTimeout as timeout:
            if timeout.output:
                if "Primitive '_GetLangPort' failed" in timeout.output:
                    raise SCLangError("sclang could not bind udp socket. "
                                      "Try killing old sclang processes.",
                                      timeout.output) from timeout
            else:
                raise
        else:
            self.started = True
            print('Done.')

            print('Registering OSC /return callback in sclang...')
            self.cmd(r'''
                // NetAddr.useDoubles = true;
                r = r ? ();
                r.callback = { arg code, ip, port;
                    var result = code.interpret;
                    var addr = NetAddr.new(ip, port);
                    var prependSize = { arg elem;
                        if (elem.class == Array){
                            elem = [elem.size] ++ elem.collect(prependSize);
                        }{
                            elem;
                        };
                    };
                    var msgContent = prependSize.value(result);
                    addr.sendMsg(^replyAddress, msgContent);
                    result;  // result should be returned
                };''', pyvars={"replyAddress": ReplyAddress.RETURN_ADDR})
            self.read(expect=self.prompt_str)
            print('Done.')

            resource_path = resources.__file__[:-len('__init__.py')].replace("\\", r"\\")
            print('Loading default SynthDescs')
            self.load_synthdefs(resource_path)
            self.read(expect=self.prompt_str)
            print('Done.')

    def load_synthdefs(self, synthdefs_path: str) -> None:
        """Load SynthDef files from path.

        Parameters
        ----------
        synthdefs_path : str
            Path where the SynthDef files are located.
        """
        self.cmd(
            r'''PathName.new(^synthdefs_path).files.collect(
              { |path| (path.extension == "scsyndef").if({SynthDescLib.global.read(path); path;})}
            );''',
            pyvars={"synthdefs_path": synthdefs_path})

    def kill(self) -> int:
        """Kill this sclang instance.

        Returns
        -------
        int
            returncode of the process.
        """
        self.started = False
        try:
            self.cmd('0.exit;')
        except RuntimeError:
            pass
        else:
            time.sleep(1)  # let sclang exit
        return self.process.kill()

    def __del__(self):
        self.kill()

    def cmd(self,
            code: str,
            pyvars: Optional[dict] = None,
            verbose: bool = False,
            discard_output: bool = True,
            get_result: bool = False,
            print_error: bool = True,
            get_output: bool = False,
            timeout: int = 1) -> Any:
        """Send code to sclang to execute it.

        This also allows to get the result of the code or the corresponding output.

        Parameters
        ----------
        code : str
            SuperCollider code to execute.
        pyvars : dict, optional
            Dictionary of name and value pairs of python
            variables that can be injected via ^name, by default None
        verbose : bool, optional
            If True print output, by default False
        discard_output : bool, optional
            If True clear output buffer before passing command, by default True
        get_result : bool, optional
            If True receive and return the
            evaluation result from sclang, by default False
        print_error : bool, optional
            If this and get_result is True and code execution fails
            the output from sclang will be printed.
        get_output : bool, optional
            If True return output. Does not override get_result
            If verbose this will be True, by default False
        timeout : int, optional
            Timeout for code execution return result, by default 1

        Returns
        -------
        Any
            if get_result=True,
                Result from SuperCollider code,
                not all SC types supported.
                When type is not understood this
                will return the datagram from the
                OSC packet.
            if get_output or verbose
                Output from SuperCollider code.
            else
                None

        Raises
        ------
        RuntimeError
            If get_result is True but no OSCCommunication instance is set.
        SCLangError
            When an error with sclang occurs.
        """
        if pyvars is None:
            pyvars = parse_pyvars(code)
        code = replace_vars(code, pyvars)

        # cleanup command string
        code = remove_comments(code)
        code = re.sub(r'\s+', ' ', code).strip()

        if get_result:
            if self._server is None:
                raise RuntimeError(
                    "get_result is only possible when connected to a SCServer")
            # escape " and \ in our SuperCollider string literal
            inner_code_escapes = str.maketrans(
                {ord('\\'): r'\\', ord('"'): r'\"'})
            inner_code = code.translate(inner_code_escapes)
            # wrap the command string with our callback function
            code = r"""r['callback'].value("{0}", "{1}", {2});""".format(
                inner_code, *self._server.osc_server.server_address)

        if discard_output:
            self.empty()  # clean all past outputs

        # write command to sclang pipe \f
        if code and code[-1] != ';':
            code += ';'
        self.process.send(code + '\n\f')

        return_val = None
        if get_result:
            try:
                return_val = self._server.returns.get(timeout)
            except Empty:
                out = self.read()
                if print_error:
                    print("ERROR: unable to receive /return message from sclang")
                    print("sclang output: (also see console) \n")
                    print(out)
                raise SCLangError(
                    "unable to receive /return message from sclang",
                    sclang_output=out)
        if verbose or get_output:
            # get output after current command
            out = self.read(expect=self.prompt_str)
            if sys.platform != 'win32':
                out = ANSI_ESCAPE.sub('', out)  # remove ansi chars
                out = out.replace('sc3>', '')  # remove prompt
                out = out[out.find(';\n') + 2:]  # skip code echo
            out = out.strip()
            if verbose:
                print(out)
            if not get_result and get_output:
                return_val = out

        return return_val

    def cmdv(self, code: str, **kwargs) -> Any:
        """cmd with verbose=True"""
        if kwargs.get("pyvars", None) is None:
            kwargs["pyvars"] = parse_pyvars(code)
        return self.cmd(code, verbose=True, **kwargs)

    def cmdg(self, code: str, **kwargs) -> Any:
        """cmd with get_result=True"""
        if kwargs.get("pyvars", None) is None:
            kwargs["pyvars"] = parse_pyvars(code)
        return self.cmd(code, get_result=True, **kwargs)

    def read(self,
             expect: Optional[str] = None,
             timeout: int = 1,
             print_error: bool = True) -> str:
        """Reads SuperCollider output from the process output queue.

        Parameters
        ----------
        expect : Optional[str], optional
            Try to read this expected string, by default None
        timeout : int, optional
            How long we try to read expected string, by default 1
        print_error : bool, optional
            If True this will print a message when timed out, by default True

        Returns
        -------
        str
            output from sclang process.

        Raises
        ------
        timeout
            If expected output string could not be read before timeout.
        """
        try:
            return self.process.read(expect=expect, timeout=timeout)
        except ProcessTimeout as timeout_error:
            if print_error:
                error_str = "Timeout while reading sclang"
                if expect:
                    error_str += (f'\nexpected: "{expect}"'
                                   ' (sclang prompt)' if expect is self.prompt_str else '')
                error_str += "\noutput until timeout below: (also see console)"
                error_str += "\n----------------------------------------------\n"
                print(error_str + timeout_error.output)
            raise timeout_error

    def empty(self) -> None:
        """Empties sc output queue."""
        self.process.empty()

    def get_synth_desc(self, synth_def):
        """Get SynthDesc via sclangs global SynthDescLib.

        Parameters
        ----------
        synth_def : str
            SynthDef name

        Returns
        -------
        dict
            {argument_name: SynthArgument(rate, default)}

        Raises
        ------
        ValueError
            When synthDesc of synthDef can not be found.
        """
        code = r"""SynthDescLib.global['{{synthDef}}'].controls.collect(
                { arg control;
                [control.name, control.rate, control.defaultValue]
                })""".replace('{{synthDef}}', synth_def)
        try:
            synth_desc = self.cmd(code, get_result=True, print_error=False)
        except SCLangError:  # this will fail if sclang does not know this synth
            warnings.warn(f"Couldn't find SynthDef {synth_def} in sclangs global SynthDescLib.")
            synth_desc = None

        if synth_desc:
            return {s[0]: SynthArgument(s[0], *s[1:]) for s in synth_desc if s[0] != '?'}
        else:
            return None

    @property
    def addr(self) -> Tuple[str, int]:
        """The address of this sclang"""
        return ("127.0.0.1", self._port)

    @property
    def server(self) -> Optional[SCServer]:
        """The SuperCollider server connected to this sclang instance."""
        return self._server

    def connect_to_server(self, server: Optional[SCServer] = None):
        """Connect this sclang instance to the SuperCollider Server.

        This will set Server.default and s to a the provided remote Server.

        Parameters
        ----------
        server : Optional[SCServer], optional
            SuperCollider Server to connect. If None try to reconnect.

        Raises
        ------
        ValueError
            If something different from a SCServer or None was provided
        SCLangError
            If sclang failed to register to the server.
        """
        if server is None:
            server = self._server
        if not isinstance(server, SCServer):
            raise ValueError(f"Server must be instance of SCServer, got {type(server)}")
        code = r"""Server.default=s=Server.remote('remote', NetAddr("{0}",{1}), clientID:{2});"""
        self.cmd(code.format(*server.addr, SC3NB_SCLANG_CLIENT_ID))
        try:  # if there are 'too many users' we failed. So the Exception is the successful case!
            self.read(expect='too many users', timeout=2, print_error=False)
        except ProcessTimeout:
            _LOGGER.info("Updated SC server at sclang")
            self._server = server
            self._port = self.cmdg('NetAddr.langPort')
            self._server.add_receiver(name="sclang", ip="127.0.0.1", port=self._port)
            _LOGGER.info('Updated sclang port on OSCCommunication '
                         'to non default port: %s', self._port)
        else:
            raise SCLangError("failed to register to the server (too many users)\n"
                              "Restart the scsynth server with maxLogins >= 3 "
                              "or specify a different server")
