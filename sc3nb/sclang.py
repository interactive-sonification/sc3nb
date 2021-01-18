"""Module for handling a SuperCollider language (sclang) process."""
import re
import sys
import inspect
import time
import warnings

from collections import namedtuple
from queue import Empty

import numpy as np

import sc3nb.resources as resources
from sc3nb.osc.osc_communication import SCLANG_DEFAULT_PORT
from sc3nb.sc_objects.server import SCServer
from sc3nb.process_handling import Process, ProcessTimeout, ALLOWED_PARENTS

SC3NB_SCLANG_CLIENT_ID = 0

ANSI_ESCAPE = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')

SynthArgument = namedtuple('SynthArgument', ['rate', 'default'])


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

    This supports currently:
        numpy.ndarray -> SC Array representation
        complex type -> SC Complex
        strings -> if starting with sc3: it will be used as SC code
                   if it starts with a \\ (single escaped backward slash) it will be used as symbol
                   else it will be inserted as string  
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


class SclangError(Exception):
    def __init__(self, message, sclang_output=None):
        super().__init__(message)
        self.sclang_output = sclang_output

class Sclang:

    def __init__(self):
        self._osc = None
        self._server = None

        if sys.platform == "linux" or sys.platform == "linux2":
            self.prompt_str = 'sc3>'
            #self._read_loop = self._read_loop_unix
        elif sys.platform == "darwin":
            self.prompt_str = 'sc3>'
            #self._read_loop = self._read_loop_unix
        elif sys.platform == "win32":
            self.prompt_str = '->'
            #self._read_loop = self._read_loop_windows
        else:
            raise NotImplementedError('Unsupported OS {}'.format(sys.platform))

        self.rec_node_id = -1  # i.e. not valid
        self.rec_bufnum = -1

        self.process = None
        
        self.port = None
        self.started = False
 
    def start(self, sclang_path=None, console_logging=True, allowed_parents=ALLOWED_PARENTS):
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
                    raise SclangError("sclang could not bind udp socket. "
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
                    addr.sendMsg("/return", msgContent);
                    result;  // result should be returned
                };''')
            self.read(expect=self.prompt_str)
            print('Done.')

            resource_path = resources.__file__[:-len('__init__.py')].replace("\\", r"\\")
            print(f'Loading SynthDesc from {resource_path}')
            self.load_synthdefs(resource_path)    
            print('Done.')

    def load_synthdefs(self, synthdefs_path):
        self.cmd(r'''PathName.new(^synthdefs_path).files.collect(
            { |path| (path.extension == "scsyndef").if({SynthDescLib.global.read(path); path;})}
            );''')

    @property
    def server(self):
        return self._server

    def connect_to_server(self, server=None):
        if server is None:
            server = self._server
        if not isinstance(server, SCServer):
            raise ValueError(f"Server must be instance of SCServer, got {type(server)}")
        cmdstr = r"""Server.default=s=Server.remote('remote', NetAddr("{0}",{1}), clientID:{2});"""
        self.cmd(cmdstr.format(*server.addr, SC3NB_SCLANG_CLIENT_ID))
        try:  # if there are 'too many users' we failed. So the Exception is the successful case!
            self.read(expect='too many users', timeout=2, print_error=False)
        except ProcessTimeout:
            print("Updated SC server at sclang")
            self._server = server
            self.connect_to_osc(server.osc)
        else:
            raise SclangError("failed to register to the server (too many users)\n"
                              "Restart the scsynth server with maxLogins >= 3 or specify a different server")
            
    @property
    def osc(self):
        return self._osc

    def connect_to_osc(self, osc):
        self._osc = osc
        if self.port is None:
            self.port = self.cmdg('NetAddr.langPort')
        if self.port != SCLANG_DEFAULT_PORT:
            self._osc.set_sclang(sclang_port=self.port)
            print('Updated sclang port on osc to non default port: {}'.format(self.port))

    def kill(self):
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

    def cmd(self, cmdstr, pyvars=None,
            verbose=False, discard_output=True,
            get_result=False, get_output=False, timeout=1):
        """Sends code to SuperCollider (sclang)

        Arguments:
            cmdstr {str} -- SuperCollider code

        Keyword Arguments:
            pyvars {dict} -- Dictionary of name and value pairs of python
                             variables that can be injected via ^name
                             (default: {None})
            verbose {bool} -- if True print output
                              (default: {False})
            discard_output {bool} -- if True clear output buffer before
                                     passing command
                                     (default: {True})
            get_result {bool} -- if True receive and return the evaluation
                                 result from sclang
                                 (default: {False})
            get_output {bool} -- if True return output if not get_result
                                 if verbose this will be True
                                 (default: {False})
            timeout {int} -- Timeout time for receiving data
                             (default: {1})

        Returns:
            {*} -- if get_result=True,
                   Output from SuperCollider code,
                   not all SC types supported.
                   When type is not understood this
                   will return the datagram from the
                   OSC packet.

        Raises:
            SclangError
                When communication with sclang fails.
            RuntimeError
                When get_result is used and no OSC is set.
        """
        if pyvars is None:
            pyvars = parse_pyvars(cmdstr)
        cmdstr = replace_vars(cmdstr, pyvars)

        # cleanup command string
        cmdstr = remove_comments(cmdstr)
        cmdstr = re.sub(r'\s+', ' ', cmdstr).strip()

        if get_result:
            if self._osc is None:
                raise RuntimeError(
                    "get_result is only possible when osc is set")
            # escape " and \ in our SuperCollider string literal
            inner_cmdstr_escapes = str.maketrans(
                {ord('\\'): r'\\', ord('"'): r'\"'})
            inner_cmdstr = cmdstr.translate(inner_cmdstr_escapes)
            # wrap the command string with our callback function
            cmdstr = r"""r['callback'].value("{0}", "{1}", {2});""".format(
                inner_cmdstr, *self._osc.server.server_address)

        if discard_output:
            self.empty()  # clean all past outputs

        # write command to sclang pipe \f
        if cmdstr and cmdstr[-1] != ';':
            cmdstr += ';'
        self.process.send(cmdstr + '\n\f')
        
        return_val = None
        if get_result:
            try:
                return_val = self._osc.returns.get(timeout)
            except Empty:
                print("ERROR: unable to receive /return message from sclang")
                print("sclang output: (also see console) \n")
                out = self.read()
                print(out)
                raise SclangError(
                    "unable to receive /return message from sclang",
                    sclang_output=out)
        if verbose or get_output:
            # get output after current command
            out = self.read(expect=self.prompt_str)
            if sys.platform != 'win32':
                out = ANSI_ESCAPE.sub('', out)  # remove ansi chars
                out = out.replace('sc3>', '')  # remove prompt
                out = out[out.find(';\n') + 2:]  # skip cmdstr echo
            out = out.strip()
            if verbose:
                print(out)
            if not get_result and get_output:
                return_val = out

        return return_val

    def cmdv(self, cmdstr, **kwargs):
        """Sends code to SuperCollider (sclang)
           and prints output

        Arguments:
            cmdstr {str} -- SuperCollider code

        Keyword Arguments:
            pyvars {dict} -- Dictionary of name and value pairs
                             of python variables that can be
                             injected via ^name
                             (default: {None})
            discard_output {bool} -- if True clear output
                                     buffer before passing
                                     command
                                     (default: {True})
            get_result {bool} -- if True receive and return
                                 the evaluation result
                                 from sclang
                                 (default: {False})
            timeout {int} -- Timeout time for receiving data
                             (default: {1})

        Returns:
            {*} -- if get_result=True,
                   Output from SuperCollider code,
                   not all SC types supported.
                   When type is not understood this
                   will return the data gram from the
                   OSC packet.
        """
        if kwargs.get("pyvars", None) is None:
            kwargs["pyvars"] = parse_pyvars(cmdstr)
        return self.cmd(cmdstr, verbose=True, **kwargs)

    def cmdg(self, cmdstr, **kwargs):
        """Sends code to SuperCollider (sclang)
           and receives and returns the evaluation result

        Arguments:
            cmdstr {str} -- SuperCollider code

        Keyword Arguments:
            pyvars {dict} -- Dictionary of name and value pairs
                             of python variables that can be
                             injected via ^name
                             (default: {None})
            verbose {bool} -- if True print output
                              (default: {False})
            discard_output {bool} -- if True clear output
                                     buffer before passing
                                     command
                                     (default: {True})
            timeout {int} -- Timeout time for receiving data
                             (default: {1})

        Returns:
            {*} -- if get_result=True,
                   Output from SuperCollider code,
                   not all SC types supported.
                   When type is not understood this
                   will return the data gram from the
                   OSC packet.
        """
        if kwargs.get("pyvars", None) is None:
            kwargs["pyvars"] = parse_pyvars(cmdstr)
        return self.cmd(cmdstr, get_result=True, **kwargs)

    def read(self, expect=None, timeout=1, print_error=True):
        '''Reads first sc output from output queue'''
        try:
            return self.process.read(expect=expect, timeout=timeout)
        except ProcessTimeout as timeout:
            if print_error:
                error_str = "Timeout while reading sclang"
                if expect:
                    error_str += (f'\nexpected: "{expect}"'
                                   ' (sclang prompt)' if expect is self.prompt_str else '')
                error_str += "\noutput until timeout below: (also see console)"
                error_str += "\n----------------------------------------------\n"
                print(error_str + timeout.output)
            raise timeout

    def empty(self):
        '''Empties sc output queue'''
        self.process.empty()

    def get_synth_desc(self, synth_def):
        """Get SynthDesc via sclang

        Parameters
        ----------
        sc : SC
            SC instance with SynthDef
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
        cmdstr = r"""SynthDescLib.global['{{synthDef}}'].controls.collect(
                { arg control;
                [control.name, control.rate, control.defaultValue]
                })""".replace('{{synthDef}}', synth_def)
        try:
            synth_desc = self.cmdg(cmdstr)
        except SclangError: # this will fail if sclang does not know this synth TODO: is this the only Error?
            warnings.warn("Couldn't find SynthDef %s with sclang" % synth_def)
            synth_desc = None

        if synth_desc:
            return {s[0]: SynthArgument(*s[1:]) for s in synth_desc if s[0] != '?'}
        else:
            return None
