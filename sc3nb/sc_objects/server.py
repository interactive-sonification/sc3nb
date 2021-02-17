"""Module for managing Server related stuff."""
from enum import Enum, unique
import logging
import warnings

from typing import Dict, List, NamedTuple, Optional, Sequence, Union, Tuple
from weakref import WeakValueDictionary
from queue import Empty
from random import randint

import sc3nb.resources as resources
from sc3nb.process_handling import Process, ProcessTimeout, ALLOWED_PARENTS

from sc3nb.osc.parsing import SYNTH_DEF_MARKER, preprocess_return
from sc3nb.osc.osc_communication import (build_message,
                                         OSCCommunication,
                                         OSCCommunicationError,
                                         MessageQueue,
                                         MessageQueueCollection)

from sc3nb.sc_objects.node import Node, Group, NodeTree
from sc3nb.sc_objects.synthdef import SynthDef

import sc3nb

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())

SC3NB_SERVER_CLIENT_ID = 1
SC3NB_DEFAULT_PORT = 57130
SCSYNTH_DEFAULT_PORT = 57110

RESOURCES_SYNTH_DEFS = resources.__file__[:-len("__init__.py")]

ASYNC_MSGS = [
    "/quit",    # Master
    "/notify",
    "/d_recv",  # Synth Def load SynthDefs
    "/d_load",
    "/d_loadDir",
    "/b_alloc",  # Buffer Commands
    "/b_allocRead",
    "/b_allocReadChannel",
    "/b_read",
    "/b_readChannel",
    "/b_write",
    "/b_free",
    "/b_zero",
    "/b_gen",
    "/b_close"
]

MSG_PAIRS = {
    # Master
    "/status": "/status.reply",
    "/sync": "/synced",
    "/version": "/version.reply",
    # Synth Commands
    "/s_get": "/n_set",
    "/s_getn": "/n_setn",
    # Group Commands
    "/g_queryTree": "/g_queryTree.reply",
    # Node Commands
    "/n_query": "/n_info",
    # Buffer Commands
    "/b_query":  "/b_info",
    "/b_get":  "/b_set",
    "/b_getn":  "/b_setn",
    # Control Bus Commands
    "/c_get":  "/c_set",
    "/c_getn":  "/c_setn"
}


class ServerStatus(NamedTuple):
    """Information about the status of the Server program"""
    num_ugens: int
    num_synths: int
    num_groups: int
    num_synthdefs: int
    avg_cpu: float
    peak_cpu: float
    nominal_sr: float
    actual_sr: float

class ServerVersion(NamedTuple):
    """Information about the version of the Server program"""
    name: str
    major_version: int
    minor_version: int
    patch_version: str
    git_branch: str
    commit: str

class ServerOptions():
    """ServerOptions encapulates the command line server options."""
    def __init__(self,
                 udp_port: int = SCSYNTH_DEFAULT_PORT,
                 max_logins: int = 15,
                 num_input_bus: int = 2,
                 num_output_bus: int = 2,
                 num_audio_bus: int = 1024,
                 publish_rendezvous: bool = False,
                 block_size: Optional[int] = None,
                 hardware_buffer_size: Optional[int] = None,
                 hardware_sample_size: Optional[int] = None,
                 hardware_input_device: Optional[str] = None,
                 hardware_output_device: Optional[str] = None,
                 other_options: Optional[Sequence[str]] = None):
        # arguments as sequence as wanted by subprocess.Popen
        self.args = []

        # UDP port
        self.udp_port = udp_port
        self.args += ["-u", f"{self.udp_port}"]

        # max logins
        if 3 <= max_logins <= 32:
            self.max_logins = max_logins
        else:
            # max_logins must be between 3 (sc3nb, sclang (sc3nb), sclang (scide)) and 32
            # see https://scsynth.org/t/how-do-i-connect-sclang-to-an-already-running-server/2498/6
            raise ValueError("max logins must be between 3 and 32")
        self.args += ["-l", f"{self.max_logins}"]

        # audio bus options
        self.num_input_bus = num_input_bus
        self.args += ["-i", f"{self.num_input_bus}"]
        self.num_output_bus = num_output_bus
        self.args += ["-o", f"{self.num_output_bus}"]
        if num_audio_bus < num_input_bus + num_output_bus:
            raise ValueError(f"You need at least {num_input_bus + num_output_bus} audio buses")
        self.num_audio_bus = num_audio_bus
        self.args += ["-a", f"{self.num_audio_bus}"]

        # publish to Rendezvous
        self.publish_rendezvous = 1 if publish_rendezvous else 0
        self.args += ["-R", f"{self.publish_rendezvous}"]

        if block_size is not None:
            self.block_size = block_size
            self.args += ["-z", f"{self.block_size}"]

        if hardware_buffer_size is not None:
            self.hardware_buffer_size = hardware_buffer_size
            self.args += ["-Z", f"{self.hardware_buffer_size}"]

        if hardware_sample_size is not None:
            self.hardware_sample_size = hardware_sample_size
            self.args += ["-S", f"{self.hardware_sample_size}"]

        # hardware in/out device
        if not hardware_input_device:
            self.hardware_input_device = ""
        else:
            self.hardware_input_device = hardware_input_device
        if not hardware_output_device:
            self.hardware_output_device = ""
        else:
            self.hardware_output_device = hardware_output_device
        if hardware_input_device or hardware_output_device:
            self.args += ["-H",
                          f"{self.hardware_input_device} {self.hardware_output_device}".strip()]

        # misc. options
        self.other_options = other_options
        if self.other_options:
            self.args += self.other_options

    def first_private_bus(self) -> int:
        # after the outs and ins
        return self.num_output_bus + self.num_input_bus

    def __repr__(self):
        return f"<ServerOptions {self.args}>"

class SCServer(OSCCommunication):
    """The SCServer represents the SuperCollider Server programm as Python object."""

    def __init__(self, server_options: Optional[ServerOptions] = None):
        # process
        if server_options is None:
            self.server_options = ServerOptions()
            _LOGGER.debug("Using default server options %s", self.server_options)
        else:
            self.server_options = server_options
            _LOGGER.debug("Using custom server options %s", self.server_options)

        super().__init__(server_ip="127.0.0.1",
                         server_port=SC3NB_DEFAULT_PORT,
                         default_receiver_ip="127.0.0.1",
                         default_receiver_port=self.server_options.udp_port)

        # init msg queues
        self.create_msg_pairs(MSG_PAIRS)

        # /return messages from sclang callback
        self.returns = MessageQueue("/return", preprocess_return)
        self.add_msg_queue(self.returns)

        # /done messages must be seperated
        self.dones = MessageQueueCollection(address="/done", sub_addrs=ASYNC_MSGS)
        self.add_msg_queue_collection(self.dones)

        self.fails = MessageQueueCollection(address="/fail")
        self.add_msg_queue_collection(self.fails)

        # set logging handlers
        self._osc_server.dispatcher.map("/fail", self._warn_fail, needs_reply_address=True)
        self._osc_server.dispatcher.map("/*", self._log_message, needs_reply_address=True)

        # node managing
        self.nodes: WeakValueDictionary[int, Node] = WeakValueDictionary()

        self._default_groups: Dict[int, Group] = {}
        self._is_local: bool = False

        # counter for nextNodeID
        self._num_node_ids: int = 0
        self._num_buffer_ids: int = 0

        self.process: Optional[Process]  = None

        self._client_id: int = SC3NB_SERVER_CLIENT_ID
        self._scsynth_address = "127.0.0.1"
        self._scsynth_port = self.server_options.udp_port
        self._max_logins = self.server_options.max_logins

        self._server_running: bool  = False
        self._has_booted: bool  = False

    def boot(self,
             scsynth_path: Optional[str] = None,
             timeout: float = 3,
             console_logging: bool = True,
             with_blip: bool = True,
             allowed_parents: Sequence[str] = ALLOWED_PARENTS):
        if self._has_booted:
            warnings.warn("already booted")
            return
        print('Booting SuperCollider Server...')
        self._is_local = True
        self._scsynth_address = "127.0.0.1"
        self._scsynth_port = self.server_options.udp_port
        self.process = Process(executable='scsynth',
                               args=self.server_options.args,
                               exec_path=scsynth_path,
                               console_logging=console_logging,
                               allowed_parents=allowed_parents)
        try:
            self.process.read(expect="SuperCollider 3 server ready.", timeout=timeout)
        except ProcessTimeout as process_timeout:
            if "Exception in World_OpenUDP" in process_timeout.output:
                # ToDo check if string is correct in Linux
                self.process.kill()
                self.process = None
                print("SuperCollider Server port already used.")
                if self.server_options.udp_port != SCSYNTH_DEFAULT_PORT:
                    raise ValueError(
                        f"The specified UDP port {self.server_options.udp_port} is already used")
                else:
                    print("Trying to connect.")
                    self.remote(self._scsynth_address, self._scsynth_port, with_blip=with_blip)
            else:
                print("Failed booting SuperCollider Server.")
                raise process_timeout
        else:
            self.init(with_blip)
            self._has_booted = True

    def init(self, with_blip: bool = True):
        # notify the supercollider server about us
        self.add_receiver("scsynth", self._scsynth_address, self._scsynth_port)
        self.notify()

        # load synthdefs of sc3nb
        self.load_synthdefs()

        # create default groups
        self.send_default_groups()

        self.sync()
        if with_blip:
            self.blip()

        print('Done.')

    def blip(self):
        with self.bundler(0.1) as bundler:
            bundler.add(0.1, "/s_new", ["s1", -1, 0, 0, "freq", 500, "dur", 0.1, "num", 1])
            bundler.add(0.3, "/s_new", ["s2", -1, 0, 0, "freq", 1000, "amp", 0.05, "num", 2])
            bundler.add(0.4, "/n_free", [-1])

    def remote(self, address: str, port: int, with_blip: bool = True):
        self._is_local = False
        self._scsynth_address = address
        self._scsynth_port = port
        self.init(with_blip=with_blip)
        self._has_booted = True

    def reboot(self):
        if not self.is_local:
            raise RuntimeError("Can't reboot a remote Server")
        self.quit()
        self.boot()

    def ping(self):
        raise NotImplementedError

    # messages
    def quit(self):
        try:
            self.send(build_message("/quit"))
        except OSCCommunicationError:
            pass  # sending failed. scscynth maybe dead already.
        finally:
            super().quit()
            if self._is_local:
                self.process.kill()

    def sync(self, timeout=5):
        """Sync the server with the /sync command.

        Parameters
        ----------
        timeout : int, optional
            Time in seconds that will be waited for sync.
             (Default value = 5)

        """
        sync_id = randint(1000, 9999)
        msg = build_message("/sync", sync_id)
        return sync_id == self.send(msg, timeout=timeout)

    def send_synthdef(self, synthdef_bytes: bytes):
        msg = build_message("/d_recv", synthdef_bytes)
        return self.send(msg)

    def load_synthdef(self, synthdef_path: str):
        msg = build_message("/d_load", synthdef_path)
        return self.send(msg)

    def load_synthdefs(self,
                       directory: Optional[str] = None,
                       completion_msg: bytes = None) -> None:
        if directory is None:
            directory = RESOURCES_SYNTH_DEFS
        args: List[Union[str, bytes]] = [directory]
        if completion_msg is not None:
            args.append(completion_msg)
        self.msg("/d_loadDir", args)

    def notify(self,
               receive_notifications: bool = True,
               client_id: Optional[int] = None,
               timeout: float = 5.0):
        flag = 1 if receive_notifications else 0
        client_id = client_id if client_id else self._client_id
        msg = build_message("/notify", [flag, client_id])  # flag, clientID
        try:
            return_val = self.send(msg, timeout=timeout)
        except OSCCommunicationError as error:
            if msg.address in self.fails:
                error_value = None
                while True:
                    try:
                        error_value = self.fails.msg_queues[msg.address].get(timeout=0)
                    except Empty:
                        break
                if error_value is not None:
                    if isinstance(error_value, tuple):
                        message, *rest = error_value
                    else:
                        message = error_value

                    if "already registered" in message:
                        self._client_id = rest[0]
                    elif "too many users" in message:
                        raise RuntimeError("scsynth has too many users. Can't notify.") from error
                    else:
                        raise error
        else:
            if len(return_val) == 2:
                self._client_id, self._max_logins = return_val

    def free_all(self, root: bool = True):
        self.msg("/g_freeAll", 0 if root else self.default_group.nodeid)
        self.msg("/clearSched")
        if root:
            self.send_default_groups()
        else:
            self.default_group.free_all()
            self.default_group.new()
        self.sync()

    def send_default_groups(self):
        client_ids = range(self._max_logins)
        def create_default_group(client_id):
            return sc3nb.Group(nodeid=2 ** 26 * client_id + 1, target=0, server=self).new()
        self._default_groups = {client: create_default_group(client) for client in client_ids}

    def next_node_id(self):
        self._num_node_ids += 1
        node_id = self._num_node_ids + 10000 * self._client_id
        return node_id

    def next_buffer_id(self):
        self._num_buffer_ids += 1
        node_id = self._num_buffer_ids + 100 * self._client_id
        return node_id

    @property
    def client_id(self):
        return self._client_id

    @property
    def max_logins(self):
        return self._max_logins

    @property
    def default_group(self):
        return self._default_groups[self._client_id]

    @property
    def input_bus(self):
        raise NotImplementedError

    @property
    def output_bus(self):
        raise NotImplementedError

    # Volume Class in Supercollider. Controls Filter Synth
    @property
    def volume(self):
        raise NotImplementedError

    @volume.setter
    def volume(self):
        raise NotImplementedError

    def mute(self):
        raise NotImplementedError

    def unmute(self):
        raise NotImplementedError

    # Information and debugging
    def version(self) -> ServerVersion:
        msg = build_message("/version")
        return ServerVersion._make(self.send(msg))

    def status(self) -> ServerStatus:
        msg = build_message("/status")
        return ServerStatus._make(self.send(msg)[1:])

    def dump_osc(self, level: int = 1):
        msg = build_message("/dumpOSC", [level])
        self.send(msg)

    def dump_tree(self, controls: bool = True):
        msg = build_message("/g_dumpTree", [0, 1 if controls else 0])
        return self.send(msg)

    def query_all_nodes(self, controls: bool = True):
        flag = 1 if controls else 0
        msg = build_message("/g_queryTree", [0, flag])
        _, *nodes_info = self.send(msg)
        return NodeTree(info=nodes_info,
                        root_nodeid=0,
                        controls_included=controls,
                        start=0,
                        server=self)

    @property
    def peak_cpu(self):
        return self.status().peak_cpu

    @property
    def avg_cpu(self):
        return self.status().peak_cpu

    @property
    def latency(self):
        raise NotImplementedError

    @latency.setter
    def latency(self):
        raise NotImplementedError

    @property
    def sample_rate(self):
        return self.status().nominal_sr

    @property
    def actual_sample_rate(self):
        return self.status().actual_sr

    @property
    def num_synths(self):
        return self.status().num_synths

    @property
    def num_groups(self):
        return self.status().num_groups

    @property
    def num_ugens(self):
        return self.status().num_ugens

    @property
    def num_synthdefs(self):
        return self.status().num_synthdefs

    @property
    def addr(self) -> Tuple[str, int]:
        return (self._scsynth_address, self._scsynth_port)

    @property
    def has_booted(self):
        return self._has_booted

    @property
    def server_running(self):
        return self._server_running

    @property
    def unresponsive(self):
        raise NotImplementedError

    @property
    def is_local(self):
        return self._is_local

    @property
    def pid(self):
        if self.is_local:
            return self.process.popen.pid
        else:
            warnings.warn("Server is not local or not booted.")

    def _log_message(self, sender, *args):
        if len(str(args)) > 55:
            args_str = str(args)[:55] + ".."
        else:
            args_str = str(args)
        _LOGGER.info("osc msg received from %s: %s",
                     self._check_sender(sender), args_str)

    def _warn_fail(self, sender, *args):
        _LOGGER.warning("Error from %s: %s",
                        self._check_sender(sender), args)


@unique
class RecorderState(Enum):
    """Different States"""
    UNPREPARED = "UNPREPARED"
    PREPARED = "PREPARED"
    RECORDING = "RECORDING"
    PAUSED = "PAUSED"


class Recorder:
    """Allows to record audio easily."""

    ## TODO rec_header, rec_format with Literal type from Buffer
    def __init__(self,
                 path: Optional[str] = "record.wav",
                 nr_channels: Optional[int] = 2,
                 rec_header="wav",
                 rec_format="int16",
                 bufsize: Optional[int] = 65536,
                 server: Optional[SCServer] = None):
        """Create and prepare a recorder.

        Parameters
        ----------
        path : str, optional
            path of recording file, by default "record.wav"
        nr_channels : int, optional
            Number of channels, by default 2
        rec_header : str, optional
            File format, by default "wav"
        rec_format : str, optional
            Recording resolution, by default "int16"
        bufsize : int, optional
            size of buffer, by default 65536
        server : SCServer, optional
            server used for recording, by default None
            if None it will use sc3nb.SC.default.server
        """
        self._state = RecorderState.UNPREPARED
        self._server = server or sc3nb.SC.default.server
        self._record_buffer = sc3nb.Buffer(server=self._server)
        self._record_synth: Optional[sc3nb.Synth] = None
        self.prepare(path, nr_channels, rec_header, rec_format, bufsize)

    def prepare(self, path, nr_channels, rec_header, rec_format, bufsize):
        """Pepare the recorder.

        Parameters
        ----------
        path : str, optional
            path of recording file, by default "record.wav"
        nr_channels : int, optional
            Number of channels, by default 2
        rec_header : str, optional
            File format, by default "wav"
        rec_format : str, optional
            Recording resolution, by default "int16"
        bufsize : int, optional
            size of buffer, by default 65536

        Raises
        ------
        RuntimeError
            When Recorder does not needs to be prepared.
        """
        if self._state != RecorderState.UNPREPARED:
            raise RuntimeError(f"Recorder state must be UNPREPARED but is {self._state}")
        # prepare buffer
        self._record_buffer.alloc(bufsize, channels=nr_channels)
        self._record_buffer.write(path=path,
                                  header=rec_header,
                                  sample=rec_format,
                                  num_frames=0,
                                  starting_frame=0,
                                  leave_open=True)
        self._rec_id = self._record_buffer.bufnum
        # TODO we could prepare the synthDef beforehand and just use the right one here.
        # This would allow Recordings without sclang
        self._synth_def = SynthDef(f"sc3nb_recording_{self._rec_id}",
        r"""{ |bus, bufnum, duration|
			var tick = Impulse.kr(1);
			var timer = PulseCount.kr(tick) - 1;
			Line.kr(0, 0, duration, doneAction: if(duration <= 0, 0, 2));
			SendReply.kr(tick, '/recordingDuration', timer, ^rec_id);
			DiskOut.ar(bufnum, In.ar(bus, ^nr_channels))
		}""")
        self._synth_name = self._synth_def.add(
            pyvars={'rec_id': self._rec_id, 'nr_channels': nr_channels})
        self._state = RecorderState.PREPARED

    def start(self,
              timestamp: Optional[float] = 0,
              duration: Optional[float] = None,
              node: Union[Node, int] = 0,
              bus: Optional[int] = 0):
        """Start the recording.

        Parameters
        ----------
        timestamp : Optional[float], optional
            Time (or time offset when <1e6) to start, by default 0
        duration : Optional[float], optional
            Length of the recording, by default until stopped.
        node : Union[Node, int], optional
            Node that should be recorded, by default 0
        bus : Optional[int], optional
            Bus that should be recorded, by default 0

        Raises
        ------
        RuntimeError
            When trying to start a recording unprepared.
        """
        if self._state != RecorderState.PREPARED:
            raise RuntimeError(f"Recorder state must be PREPARED but is {self._state}")
        args = dict(bus=bus,
                    duration=duration if duration else -1,
                    bufnum=self._record_buffer.bufnum)
        with self._server.bundler(timestamp=timestamp):
            self._record_synth = sc3nb.Synth(self._synth_name,
                                            args=args,
                                            server=self._server,
                                            target=node,
                                            add_action=sc3nb.AddAction.TO_TAIL)
        self._state = RecorderState.RECORDING

    def pause(self, timestamp: Optional[float] = 0):
        """Pause the recording.

        Parameters
        ----------
        timestamp : Optional[float], optional
            Time (or time offset when <1e6) to pause, by default 0

        Raises
        ------
        RuntimeError
            When trying to pause if not recording.
        """
        if self._state != RecorderState.RECORDING:
            raise RuntimeError(f"Recorder state must be RECORDING but is {self._state}")
        with self._server.bundler(timestamp=timestamp):
            self._record_synth.run(False)
        self._state = RecorderState.PAUSED

    def resume(self, timestamp: Optional[float] = 0):
        """Resume the recording

        Parameters
        ----------
        timestamp : Optional[float], optional
            Time (or time offset when <1e6) to resume, by default 0

        Raises
        ------
        RuntimeError
            When trying to resume if not paused.
        """
        if self._state != RecorderState.PAUSED:
            raise RuntimeError(f"Recorder state must be PAUSED but is {self._state}")
        with self._server.bundler(timestamp=timestamp):
            self._record_synth.run(True)
        self._state = RecorderState.RECORDING

    def stop(self, timestamp: Optional[float] = 0):
        """Stop the recording.

        Parameters
        ----------
        timestamp : Optional[float], optional
            Time (or time offset when <1e6) to stop, by default 0

        Raises
        ------
        RuntimeError
            When trying to stop if not started.
        """
        if self._state in [RecorderState.RECORDING, RecorderState.PAUSED]:
            with self._server.bundler(timestamp=timestamp):
                self._record_synth.free()
                self._record_synth = None
                self._record_buffer.close()
            self._state = RecorderState.UNPREPARED
        else:
            raise RuntimeError(f"Recorder state must be RECORDING or PAUSED but is {self._state}")

    def __repr__(self) -> str:
        return f"<Recorder [{self._state.value}]>"

    def __del__(self):
        try:
            self.stop()
        except RuntimeError:
            pass
        self._record_buffer.free()
