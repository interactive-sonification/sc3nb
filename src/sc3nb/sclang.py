"""Module for handling a SuperCollider language (sclang) process."""
import logging
import re
import sys
import time
import warnings
from pathlib import Path
from queue import Empty
from typing import Any, NamedTuple, Optional, Sequence, Tuple

if sys.version_info < (3, 9):
    # `importlib.resources` backported to PY<37 as `importlib_resources`.
    import importlib_resources as libresources
else:
    # only PY>=39 `importlib.resources` offers .files.
    import importlib.resources as libresources

import sc3nb.resources
from sc3nb.process_handling import ALLOWED_PARENTS, Process, ProcessTimeout
from sc3nb.sc_objects.server import ReplyAddress, SCServer
from sc3nb.util import parse_pyvars, remove_comments, replace_vars

_LOGGER = logging.getLogger(__name__)


SCLANG_DEFAULT_PORT = 57120
SC3NB_SCLANG_CLIENT_ID = 0


class SynthArgument(NamedTuple):
    """Synth argument, rate and default value"""

    name: str
    rate: str
    default: Any


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
        self.process: Process = None
        self._server: Optional[SCServer] = None
        self.started: bool = False
        self._port: int = SCLANG_DEFAULT_PORT
        self._repl_return = "->"
        if sys.platform.startswith("linux") or sys.platform == "darwin":
            self.ending = "\n"
        elif sys.platform == "win32":
            self.ending = "\n\f"
        else:
            raise NotImplementedError("Unsupported OS {}".format(sys.platform))

    def start(
        self,
        sclang_path: Optional[str] = None,
        console_logging: bool = True,
        allowed_parents: Sequence[str] = ALLOWED_PARENTS,
        timeout: float = 10,
    ) -> None:
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
        timeout : float, optional
            timeout in seconds for starting the executable, by default 10

        Raises
        ------
        SCLangError
            When starting or initilizing sclang failed.
        """
        if self.started:
            warnings.warn("sclang arlready started")
            return
        print("Starting sclang process... ", end="")
        self.process = Process(
            executable="sclang",
            executable_path=sclang_path,
            console_logging=console_logging,
            allowed_parents=allowed_parents,
        )
        try:
            self.read(expect="Welcome to SuperCollider", timeout=timeout)
        except ProcessTimeout as process_timeout:
            if (
                process_timeout.output
                and "Primitive '_GetLangPort' failed" in process_timeout.output
            ):
                raise SCLangError(
                    "sclang could not bind udp socket. Try killing old sclang processes.",
                    process_timeout.output,
                ) from process_timeout

            raise process_timeout
        else:
            self.started = True
            print("Done.")
            self.init()

    def init(self):
        """Initialize sclang for sc3nb usage.

        This will register the /return callback in sclang and load the SynthDefs from sc3nb.

        This is done automatically by running start.
        """
        print("Registering OSC /return callback in sclang... ", end="")
        self.cmds(
            r"""
                "sc3nb - Registering OSC /return callback".postln;
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
                };""",
            pyvars={"replyAddress": ReplyAddress.RETURN_ADDR},
        )
        print("Done.")

        print("Loading default sc3nb SynthDefs... ", end="")
        self.load_synthdefs()
        print("Done.")

    def load_synthdefs(self, synthdefs_path: Optional[str] = None) -> None:
        """Load SynthDef files from path.

        Parameters
        ----------
        synthdefs_path : str, optional
            Path where the SynthDef files are located.
            If no path provided, load default sc3nb SynthDefs.
        """

        def _load_synthdef(path):
            self.cmds(
                r""" "sc3nb - Loading SynthDefs from ^synthdef_path".postln;
                PathName.new(^synthdefs_path).files.collect(
                { |path| (path.extension == "scsyndef").if({SynthDescLib.global.read(path); path;})}
                );""",
                pyvars={"synthdefs_path": path.as_posix()},
            )

        if synthdefs_path is None:
            ref = libresources.files(sc3nb.resources) / "synthdefs"
            with libresources.as_file(ref) as path:
                _load_synthdef(path)
        else:
            path = Path(synthdefs_path)
            if path.exists() and path.is_dir():
                _load_synthdef(path)
            else:
                raise ValueError(f"Provided path {path} does not exist or is not a dir")

    def kill(self) -> int:
        """Kill this sclang instance.

        Returns
        -------
        int
            returncode of the process.
        """
        print("Exiting sclang... ", end="")
        self.started = False
        try:
            self.cmds('"sc3nb - exiting sclang".postln; 0.exit;')
        except RuntimeError:
            pass
        else:
            self.process.popen.wait(1.0)  # let sclang exit
        print("Done.")
        return self.process.kill()

    def __del__(self):
        if self.started:
            self.kill()

    def __repr__(self) -> str:
        return f"<SCLang process={self.process}>"

    def cmd(
        self,
        code: str,
        pyvars: Optional[dict] = None,
        verbose: bool = True,
        discard_output: bool = True,
        get_result: bool = False,
        print_error: bool = True,
        get_output: bool = False,
        timeout: int = 1,
    ) -> Any:
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
            If True print output, by default True
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
            Timeout in seconds for code execution return result, by default 1

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
            if get_output and get_result=True
                (result, output)
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
        code = re.sub(r"\s+", " ", code).strip()

        if get_result:
            if self._server is None:
                raise RuntimeError(
                    "get_result is only possible when connected to a SCServer"
                )
            # escape " and \ in our SuperCollider string literal
            inner_code_escapes = str.maketrans({ord("\\"): r"\\", ord('"'): r"\""})
            inner_code = code.translate(inner_code_escapes)
            # wrap the command string with our callback function
            code = r"""r['callback'].value("{0}", "{1}", {2});""".format(
                inner_code, *self._server.osc_server.server_address
            )

        if discard_output:
            self.empty()  # clean all past outputs

        # write command to sclang pipe \f
        if code and code[-1] != ";":
            code += ";"
        self.process.write(code + self.ending)

        return_val = None
        if get_result:
            try:
                return_val = self._server.returns.get(timeout)
            except Empty as empty_exception:
                out = self.read()
                if print_error:
                    print("ERROR: unable to receive /return message from sclang")
                    print("sclang output: (also see console) \n")
                    print(out)
                raise SCLangError(
                    "unable to receive /return message from sclang", sclang_output=out
                ) from empty_exception
        out = self.read(expect=self._repl_return, timeout=timeout)
        if verbose:
            if sys.platform == "darwin":
                out = out[out.find(";\n") + 2 :]  # skip code echo
            print(out)
        if get_output:
            return_val = (return_val, out) if get_result else out
        return return_val

    def cmdv(self, code: str, **kwargs) -> Any:
        """cmd with verbose=True"""
        if kwargs.get("pyvars", None) is None:
            kwargs["pyvars"] = parse_pyvars(code)
        return self.cmd(code, verbose=True, **kwargs)

    def cmds(self, code: str, **kwargs) -> Any:
        """cmd with verbose=False, i.e. silent"""
        if kwargs.get("pyvars", None) is None:
            kwargs["pyvars"] = parse_pyvars(code)
        return self.cmd(code, verbose=False, **kwargs)

    def cmdg(self, code: str, **kwargs) -> Any:
        """cmd with get_result=True"""
        if kwargs.get("pyvars", None) is None:
            kwargs["pyvars"] = parse_pyvars(code)
        return self.cmd(code, get_result=True, **kwargs)

    def read(
        self, expect: Optional[str] = None, timeout: float = 1, print_error: bool = True
    ) -> str:
        """Reads SuperCollider output from the process output queue.

        Parameters
        ----------
        expect : Optional[str], optional
            Try to read this expected string, by default None
        timeout : float, optional
            How long we try to read the expected string in seconds, by default 1
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
                    error_str += (
                        f'\nexpected: "{expect}"' " (sclang return value)"
                        if expect is self._repl_return
                        else ""
                    )
                error_str += "\noutput until timeout below: (also see console)"
                error_str += "\n----------------------------------------------\n"
                print(error_str + timeout_error.output)
            raise timeout_error

    def empty(self) -> None:
        """Empties sc output queue."""
        self.process.empty()

    def get_synth_description(self, synth_def):
        """Get a SynthDesc like description via sclang's global SynthDescLib.

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
        code = r""" "sc3nb - Get SynthDesc of {{synthDef}}".postln;
                SynthDescLib.global['{{synthDef}}'].notNil.if({
                    SynthDescLib.global['{{synthDef}}'].controls.collect(
                        { | control | [control.name, control.rate, control.defaultValue] }
                    )
                })""".replace(
            "{{synthDef}}", synth_def
        )
        synth_desc = self.cmds(code, get_result=True, print_error=False)
        if synth_desc:
            return {
                s[0]: SynthArgument(s[0], *s[1:]) for s in synth_desc if s[0] != "?"
            }
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
        """Connect this sclang instance to the SuperCollider server.

        This will set Server.default and s to the provided remote server.

        Parameters
        ----------
        server : SCServer, optional
            SuperCollider server to connect. If None try to reconnect.

        Raises
        ------
        ValueError
            If something different from an SCServer or None was provided
        SCLangError
            If sclang failed to register to the server.
        """
        if server is None:
            server = self._server
        if not isinstance(server, SCServer):
            raise ValueError(f"Server must be instance of SCServer, got {type(server)}")
        code = r""" "sc3nb - Connecting sclang to scsynth".postln;
        Server.default=s=Server.remote('sc3nb_remote', NetAddr("{0}",{1}), clientID:{2});"""
        self.cmds(code.format(*server.addr, SC3NB_SCLANG_CLIENT_ID))
        try:  # if there are 'too many users' we failed. So the Exception is the successful case!
            self.read(expect="too many users", timeout=0.3, print_error=False)
        except ProcessTimeout:
            self._server = server
            self._port = self.cmdg("NetAddr.langPort", verbose=False)
            _LOGGER.info("Connecting %s with %s", self._server, self)
            self._server.connect_sclang(port=self._port)
            self._server.add_init_hook(self.cmds, "s.initTree;")
        else:
            raise SCLangError(
                "failed to register to the server (too many users)\n"
                "Restart the scsynth server with maxLogins >= 3 "
                "or specify a different server"
            )
