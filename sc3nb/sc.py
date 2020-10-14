"""Contains classes enabling the easy communication with SuperCollider
within jupyter notebooks
"""

import os
import re
import subprocess
import sys
import threading
import time
from queue import Empty, Queue

from IPython import get_ipython
from IPython.core.magic import Magics, cell_magic, line_magic, magics_class

from .buffer import Buffer
from .synth import Synth, SynthDef
from .osc_communication import SCLANG_DEFAULT_PORT, OscCommunication
from .tools import (find_executable, parse_pyvars,
                    remove_comments, replace_vars)

if os.name == 'posix':
    import fcntl   # pylint: disable=import-error

ANSI_ESCAPE = re.compile(r'\x1B\[[0-?]*[ -/]*[@-~]')


class SclangTimeoutError(TimeoutError):
    def __init__(self, *args, sclang_output=None):
        super().__init__(args)
        self.sclang_output = sclang_output

class SC():
    """SC is a class to start SuperCollider language as subprocess
    and control it via a pipe. Communication with scsynth is handled
    by OSC messages via. Jupyter magic commands allow for simple
    execution of SuperCollider code within jupyter notebooks.
    (c) 2016-19 thermann@techfak.uni-bielefeld.de

    Keyword Arguments:
        sclangpath {str} -- Path to sclang
                            (default: {None})

    Raises:
        NotImplementedError -- Raised if
                               unsupported OS is found
    """

    sc = None

    def __init__(self, sclangpath=None, console_logging=True):

        SC.sc = self

        self.console_logging = console_logging

        if sys.platform == "linux" or sys.platform == "linux2":
            self.terminal_symbol = 'sc3>'
            self.__read_loop = self.__read_loop_unix
        elif sys.platform == "darwin":
            self.terminal_symbol = 'sc3>'
            self.__read_loop = self.__read_loop_unix
        elif sys.platform == "win32":
            self.terminal_symbol = '->'
            self.__read_loop = self.__read_loop_windows
        else:
            raise NotImplementedError('Unsupported OS {}'.format(sys.platform))

        # toggle variable to know if server has been started when exiting
        self.server = False

        # add sclang path to if environment if not already found
        if sclangpath is not None:
            sclangpath = os.path.split(sclangpath)
            if 'sclang' in sclangpath[1]:
                sclangpath = sclangpath[0]
            else:
                sclangpath = os.path.join(*sclangpath)
            if sclangpath not in os.environ['PATH']:
                os.environ['PATH'] += os.pathsep + sclangpath
        else:
            sclangpath = ''

        # find sclang in environment
        sclangpath = find_executable('sclang', path=sclangpath)

        self.sc_end_marker_prog = '("finished"+"booting").postln;'
        # hack to print 'finished booting' without having 'finished booting'
        # in the code needed for MacOS since sclang echos input.
        # In consequence the read_loop_unix() waiting for the
        # 'finished booting' string returns too early...
        # TODO: open issue for sc3 github
        #       asking for 'no echo' command line option macos sclang

        # sclang subprocess
        self.scp = subprocess.Popen(
            args=[sclangpath],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT)

        self.rec_node_id = -1  # i.e. not valid
        self.rec_bufnum = -1

        self.scp_queue = Queue()

        scp_thread = threading.Thread(target=self.__read_loop, args=(
            self.scp.stdout, self.scp_queue))
        scp_thread.daemon = True
        scp_thread.start()

        print('Starting sclang...')

        try:
            self.__scpout_read(timeout=10, terminal='Welcome to SuperCollider')
        except SclangTimeoutError as e:
            if e.sclang_output:
                if "Primitive '_GetLangPort' failed" in e.sclang_output:
                    raise ChildProcessError("sclang could not bind udp socket. "
                                            "Try killing old sclang processes.") from e


        print('Done.')

        self.osc = OscCommunication()
        self.msg = self.osc.msg
        self.bundle = self.osc.bundle
        self.msg_queues = self.osc.msg_queues
        self.update_msg_queues = self.osc.update_msg_queues
        self.sync = self.osc.sync
        self.get_connection_info = self.osc.get_connection_info

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
        self.__scpout_read(terminal=self.terminal_symbol)
        print('Done.')

        sclang_port = self.cmdg('NetAddr.langPort')
        if sclang_port != SCLANG_DEFAULT_PORT:
            self.osc.set_sclang(sclang_port=sclang_port)
            print('sclang started on non default port: {}'.format(sclang_port))

        # counter for nextNodeID
        self.num_ids = 0
        self.num_buffer_ids = 0

        # clear output buffer
        self.__scpout_empty()

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
            ChildProcessError
                When communication with sclang fails
        """
        if pyvars is None:
            pyvars = parse_pyvars(cmdstr)
        cmdstr = replace_vars(cmdstr, pyvars)

        # cleanup command string
        cmdstr = remove_comments(cmdstr)
        cmdstr = re.sub(r'\s+', ' ', cmdstr).strip()

        if get_result:
            # escape " and \ in our SuperCollider string literal
            inner_cmdstr_escapes = str.maketrans(
                {ord('\\'): r'\\', ord('"'): r'\"'})
            inner_cmdstr = cmdstr.translate(inner_cmdstr_escapes)
            # wrap the command string with our callback function
            cmdstr = r"""r['callback'].value("{0}", "{1}", {2});""".format(
                inner_cmdstr, *self.osc.server.server_address)

        if discard_output:
            self.__scpout_empty()  # clean all past outputs

        # write command to sclang pipe \f
        if cmdstr and cmdstr[-1] != ';':
            cmdstr += ';'
        self.scp.stdin.write(bytearray(cmdstr + '\n\f', 'utf-8'))
        self.scp.stdin.flush()

        return_val = None

        if get_result:
            try:
                return_val = self.osc.returns.get(timeout)
            except Empty:
                print("ERROR: unable to receive /return message from sclang")
                print("sclang output: (also see console) \n")
                print(self.__scpout_read())
                raise ChildProcessError(
                    "unable to receive /return message from sclang")

        if verbose or get_output:
            # get output after current command
            out = self.__scpout_read(terminal=self.terminal_symbol)
            if sys.platform != 'win32':
                out = ANSI_ESCAPE.sub('', out)  # remove ansi chars
                out = out.replace('sc3>', '')  # remove prompt
                out = out[out.find(';\n') + 2:]  # skip cmdstr echo
            out = out.strip()
            if verbose:
                print(out)
            if not get_result:
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

    def boot(self):
        """Boots SuperCollider server
        """
        print('Booting server...')

        self.cmd('s.boot.doWhenBooted({' + self.sc_end_marker_prog + '})')

        self.server = True

        self.__scpout_read(terminal='finished booting')

        print('Done.')

    def free_all(self):
        """Frees all SuperCollider synths (executes s.freeAll)
        """

        self.cmd("s.freeAll")

    def next_node_id(self):
        """Returns the next node ID, starting at 10000, not clientID based"""
        self.num_ids += 1
        node_id = self.num_ids + 10000
        return node_id

    def next_buffer_id(self):
        """Returns the next bufferID, starting at 100, not clientID based
        """

        self.num_buffer_ids += 1
        return self.num_buffer_ids + 100

    def exit(self):
        """Closes SuperCollider and shuts down server
        """

        if SC.sc == self:
            if self.server:
                self.__s_quit()
        self.osc.exit()
        print("Killing sclang subprocess")
        self.scp.kill()
        self.scp.wait()
        print(f"Done. ")

    def boot_with_blip(self):
        """Boots SuperCollider server with audio feedback
        """

        print('Booting scsynth...')

        self.server = True

        # make sure SC is booted and knows this synths:
        self.cmd(r"""
            Server.default = s = Server.local;
            o = Server.default.options;
            o.maxLogins = 2;
            s.boot.doWhenBooted(
            { Routine({
            /* synth definitions *********************************/
            "load synth definitions".postln;
            SynthDef("s1",
                { | freq=400, dur=0.4, att=0.01, amp=0.3, num=4, pan=0 |
                    Out.ar(0, Pan2.ar(Blip.ar(freq,  num)*
                    EnvGen.kr(Env.perc(att, dur, 1, -2), doneAction: 2),
                    pan, amp))
                }).add();
            SynthDef("s2",
                { | freq=400, amp=0.3, num=4, pan=0, lg=0.1 |
                    Out.ar(0, Pan2.ar(Blip.ar(freq.lag(lg),  num),
                              pan.lag(lg), amp.lag(lg)))
                }).add();
            SynthDef("record-2ch",
                { | bufnum |
                    DiskOut.ar(bufnum, In.ar(0, 2));
                }).add();
            SynthDef("record-1ch",
                { | bufnum |
                    DiskOut.ar(bufnum, In.ar(0, 1));
                }).add();
            SynthDef("pb-1ch",
                { |out=0, bufnum=0, rate=1, loop=0, pan=0, amp=0.3 |
                    var sig = PlayBuf.ar(1, bufnum,
                        rate*BufRateScale.kr(bufnum),
                        loop: loop,
                        doneAction: 2);
                    Out.ar(out, Pan2.ar(sig, pan, amp))
                }).add();
            SynthDef("pb-2ch",
                { |out=0, bufnum=0, rate=1, loop=0, pan=0, amp=0.3 |
                    var sig = PlayBuf.ar(2, bufnum,
                        rate*BufRateScale.kr(bufnum),
                        loop: loop,
                        doneAction: 2);
                    Out.ar(out, Balance2.ar(sig[0], sig[1], pan, amp))
                }).add();
            s.sync;
            /* test signals ****************************************/
            "create test signals".postln;
            Synth.new(\s1, [\freq, 500, \dur, 0.1, \num, 1]);
            0.2.wait;
            x = Synth.new(\s2, [\freq, 1000, \amp, 0.05, \num, 2]);
            0.1.wait;
            x.free;""" + self.sc_end_marker_prog + r"""}).play} , 1000);
        """)
        self.__scpout_read(timeout=10, terminal='finished booting')

        print('Registering to scsynth...')
        self.msg("/notify", 1)  # notify scsynth about us.

        print('Done.')

    def prepare_for_record(self, onset=0, wavpath="record.wav",
                           bufnum=99, nr_channels=2, rec_header="wav",
                           rec_format="int16"):
        """Setup recording via scsynth

        Keyword Arguments:
            onset {int} -- Bundle timetag (default: {0})
            wavpath {str} -- Save file path
                             (default: {"record.wav"})
            bufnum {int} -- Buffer number (default: {99})
            nr_channels {int} -- Number of channels
                                 (default: {2})
            rec_header {str} -- File format
                                (default: {"wav"})
            rec_format {str} -- Recording resolution
                                (default: {"int16"})
        """

        self.rec_bufnum = bufnum
        self.bundle(
            onset,
            "/b_alloc",
            [self.rec_bufnum, 65536, nr_channels])
        self.bundle(
            onset,
            "/b_write",
            [self.rec_bufnum, wavpath, rec_header, rec_format, 0, 0, 1])

    def record(self, onset=0, node_id=2001, nr_channels=2):
        """Start recording

        Keyword Arguments:
            onset {int} -- Bundle timetag (default: {0})
            node_id {int} -- SuperCollider Node id
                             (default: {2001})
        """

        self.rec_node_id = node_id
        if nr_channels == 1:
            self.bundle(
                onset,
                "/s_new",
                ["record-1ch",
                 self.rec_node_id, 1, 0, "bufnum", self.rec_bufnum])
        else:
            self.bundle(
                onset,
                "/s_new",
                ["record-2ch",
                 self.rec_node_id, 1, 0, "bufnum", self.rec_bufnum])
            # action = 1 = addtotail

    def stop_recording(self, onset=0):
        """Stop recording

        Keyword Arguments:
            onset {int} -- Bundle timetag (default: {0})
        """

        self.bundle(onset, "/n_free", [self.rec_node_id])
        self.bundle(onset, "/b_close", [self.rec_bufnum])
        self.bundle(onset, "/b_free", [self.rec_bufnum])

    def midi_ctrl_synth(self, synthname='syn'):
        """Set up MIDI control synth

        Keyword Arguments:
            synthname {str} -- Name of synth
                               (default: {'syn'})
        """

        self.cmd(r"""
            MIDIIn.connectAll;
            n.free;
            n = MIDIFunc.noteOn(
                { | level, pitch |
                    var amp = ((level-128)/8).dbamp;
                    Synth.new(^synthname, [\freq, pitch.midicps, \amp, amp]);
                    [pitch, amp].postln
                });
            """, pyvars={"synthname": synthname})

    def midi_ctrl_free(self):
        """Free MIDI control synth
        """

        self.cmd("n.free")

    def midi_gate_synth(self, synthname='syn'):
        """Set up MIDI gate synth

        Keyword Arguments:
            synthname {str} -- Name of synth
                               (default: {'syn'})
        """

        self.cmd(r"""
            MIDIIn.connectAll;
            q = q ? ();
            // q.on.free;
            // q.off.free;
            // array has one slot per possible MIDI note
            q.notes = Array.newClear(128);
            q.on = MIDIFunc.noteOn({ |veloc, num, chan, src|
                q.notes[num] = Synth.new(
                    ^synthname,
                    [\freq, num.midicps, \amp, veloc * 0.00315]);
            });
            q.off = MIDIFunc.noteOff({ |veloc, num, chan, src|
                q.notes[num].release;
            });
            q.freeMIDI = { q.on.free; q.off.free; };
            """, pyvars={"synthname": synthname})

    def midi_gate_free(self):
        """Free MIDI gate synth
        """
        self.cmd("q.on.free; q.off.free")

    def __del__(self):
        '''Handles clean deletion of object'''
        self.exit()

    def __s_quit(self):
        '''Quits the server'''
        print('Shutting down server...')

        self.cmd('s.quit')

        if sys.platform in ["linux", "linux2", "darwin"]:
            self.__scpout_read(terminal='RESULT = 0')
        elif sys.platform == "win32":
            self.__scpout_read(terminal='exit code 0.')

        self.server = False

        print('Done.')

    def __scpout_read(self, timeout=1, terminal=None):
        '''Reads first sc output from output queue'''
        timeout = time.time() + timeout
        out = ''
        terminal_found = False
        try:
            while True:
                if time.time() >= timeout:
                    raise SclangTimeoutError('timeout when reading SC stdout')
                try:
                    retbytes = self.scp_queue.get_nowait()
                    if retbytes is not None:
                        out += retbytes.decode()
                        if terminal is not None and re.search(terminal, out):
                            terminal_found = True
                except Empty:
                    if terminal and not terminal_found:
                        pass
                    else:
                        return out
                time.sleep(0.001)
        except SclangTimeoutError as e:
            print("ERROR: Timeout while reading sclang")
            print("sclang output until timeout: (also see console)\n")
            print(out)
            e.sclang_output = out
            raise

    def __scpout_empty(self):
        '''Empties sc output queue'''
        while True:
            try:
                self.scp_queue.get_nowait()
            except Empty:
                return

    def __read_loop_windows(self, output, queue):
        for line in iter(output.readline, b''):
            queue.put(line)
            if self.console_logging:
                # print to jupyter console...
                os.write(1, line)

    def __read_loop_unix(self, output, queue):
        file_descriptor = output.fileno()
        file_flags = fcntl.fcntl(file_descriptor, fcntl.F_GETFL)
        fcntl.fcntl(output, fcntl.F_SETFL, file_flags | os.O_NONBLOCK)
        while True:
            try:
                out = output.read()
                if out:
                    queue.put(out)
                    if self.console_logging:
                        # to remove ansi chars
                        out = ANSI_ESCAPE.sub('', out.decode())
                        # print to jupyter console...
                        os.write(1, out.encode())
            except EOFError:
                pass
            time.sleep(0.001)

    def Buffer(self, *args, **kwargs):
        """
        Documentation see: :class:`Buffer`
        """
        return Buffer(self, *args, **kwargs)

    def Synth(self, *args, **kwargs):
        """
        Documentation see: :class:`Synth`
        """
        return Synth(self, *args, **kwargs)

    def SynthDef(self, *args, **kwargs):
        """
        Documentation see: :class:`SynthDef`
        """
        return SynthDef(self, *args, **kwargs)


def startup(boot=True, magic=True, **kwargs):
    """Starts SC, boots scsynth and registers magics

    Keyword Arguments:
        boot {bool} -- if True boot scsynth
                       (default: {True})
        magic {bool} -- if True register jupyter magics
                        (default: {True})

    Returns:
        SC -- Communicates with and controls SuperCollider
    """

    sc = SC(**kwargs)
    if boot:
        sc.boot_with_blip()
    sc.cmdv('\"sc3nb started\";')
    if magic:
        ipy = get_ipython()
        if ipy is not None:
            ipy.register_magics(SC3Magics)
    return sc

# SC3 magics


@magics_class
class SC3Magics(Magics):
    """Jupyter magics for SC class
    """

    @cell_magic
    @line_magic
    def sc(self, line='', cell=None):
        """Execute SuperCollider code via magic

        Keyword Arguments:
            line {str} -- Line of SuperCollider code (default: {''})
            cell {str} -- Cell of SuperCollider code (default: {None})
        """

        if line:
            pyvars = self.__parse_pyvars(line)
            SC.sc.cmd(line, pyvars=pyvars)
        if cell:
            pyvars = self.__parse_pyvars(cell)
            SC.sc.cmd(cell, pyvars=pyvars)

    @cell_magic
    @line_magic
    def scv(self, line='', cell=None):
        """Execute SuperCollider code with verbose output

        Keyword Arguments:
            line {str} -- Line of SuperCollider code (default: {''})
            cell {str} -- Cell of SuperCollider code (default: {None})
        """

        if line:
            pyvars = self.__parse_pyvars(line)
            SC.sc.cmdv(line, pyvars=pyvars)
        if cell:
            pyvars = self.__parse_pyvars(cell)
            SC.sc.cmdv(cell, pyvars=pyvars)

    @cell_magic
    @line_magic
    def scg(self, line='', cell=None):
        """Execute SuperCollider code returning output

        Keyword Arguments:
            line {str} -- Line of SuperCollider code (default: {''})
            cell {str} -- Cell of SuperCollider code (default: {None})

        Returns:
            {*} -- Output from SuperCollider code, not
                   all SC types supported, see
                   pythonosc.osc_message.Message for list
                   of supported types
        """

        if line:
            pyvars = self.__parse_pyvars(line)
            return SC.sc.cmdg(line, pyvars=pyvars)
        if cell:
            pyvars = self.__parse_pyvars(cell)
            return SC.sc.cmdg(cell, pyvars=pyvars)

    @cell_magic
    @line_magic
    def scgv(self, line='', cell=None):
        """Execute SuperCollider code returning output

        Keyword Arguments:
            line {str} -- Line of SuperCollider code (default: {''})
            cell {str} -- Cell of SuperCollider code (default: {None})

        Returns:
            {*} -- Output from SuperCollider code, not
                   all SC types supported, see
                   pythonosc.osc_message.Message for list
                   of supported types
        """

        if line:
            pyvars = self.__parse_pyvars(line)
            return SC.sc.cmdg(line, pyvars=pyvars, verbose=True)
        if cell:
            pyvars = self.__parse_pyvars(cell)
            return SC.sc.cmdg(cell, pyvars=pyvars, verbose=True)

    def __parse_pyvars(self, cmdstr):
        """Parses SuperCollider code grabbing python variables
        and their values
        """

        matches = re.findall(r'\s*\^[A-Za-z_]\w*\s*', cmdstr)

        pyvars = {match.split('^')[1].strip(): None for match in matches}

        user_ns = self.shell.user_ns

        for pyvar in pyvars:
            if pyvar in user_ns:
                pyvars[pyvar] = user_ns[pyvar]
            else:
                raise NameError('name \'{}\' is not defined'.format(pyvar))

        return pyvars


try:
    if sys.platform == "linux" or sys.platform == "linux2":
        get_ipython().run_cell_magic('javascript', '',
                                     '''Jupyter.keyboard_manager.command_shortcuts.add_shortcut(
                                        \'Ctrl-.\', {
                                        help : \'sc.cmd("s.freeAll")\',
                                        help_index : \'zz\',
                                        handler : function (event) {
                                            IPython.notebook.kernel.execute("sc.cmd(\'s.freeAll\')")
                                            return true;}
                                    });''')
    elif sys.platform == "darwin":
        get_ipython().run_cell_magic('javascript', '',
                                     '''Jupyter.keyboard_manager.command_shortcuts.add_shortcut(
                                        \'cmd-.\', {
                                        help : \'sc.cmd("s.freeAll")\',
                                        help_index : \'zz\',
                                        handler : function (event) {
                                            IPython.notebook.kernel.execute("sc.cmd(\'s.freeAll\')")
                                            return true;}
                                    });''')
    elif sys.platform == "win32":
        get_ipython().run_cell_magic('javascript', '',
                                     '''Jupyter.keyboard_manager.command_shortcuts.add_shortcut(
                                        \'Ctrl-.\', {
                                        help : \'sc.cmd("s.freeAll")\',
                                        help_index : \'zz\',
                                        handler : function (event) {
                                            IPython.notebook.kernel.execute("sc.cmd(\'s.freeAll\')")
                                            return true;}
                                    });''')
except AttributeError:
    pass
