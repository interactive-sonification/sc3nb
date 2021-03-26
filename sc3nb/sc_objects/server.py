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

from sc3nb.osc.parsing import preprocess_return
from sc3nb.osc.osc_communication import (
    build_message,
    OSCCommunication,
    OSCCommunicationError,
    MessageQueue,
    MessageQueueCollection,
)

from sc3nb.sc_objects.synthdef import SynthDefinitionCommand
from sc3nb.sc_objects.buffer import BufferCommand, BufferReply
from sc3nb.sc_objects.bus import ControlBusCommand, BusRate, Bus
from sc3nb.sc_objects.node import (
    GroupCommand,
    SynthCommand,
    NodeCommand,
    NodeReply,
    GroupReply,
    Node,
    Group,
    NodeTree,
)


_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())


@unique
class MasterControlReply(str, Enum):
    """Reply addresses of the Master Control Commands."""

    VERSION_REPLY = "/version.reply"
    SYNCED = "/synced"
    STATUS_REPLY = "/status.reply"


@unique
class MasterControlCommand(str, Enum):
    """Master Control commands of scsynth."""

    DUMP_OSC = "/dumpOSC"
    STATUS = "/status"
    VERSION = "/version"
    CLEAR_SCHED = "/clearSched"
    NOTIFY = "/notify"
    QUIT = "/quit"
    SYNC = "/sync"


@unique
class ReplyAddress(str, Enum):
    """Specific reply addresses."""

    WILDCARD_ADDR = "/*"
    FAIL_ADDR = "/fail"
    DONE_ADDR = "/done"
    RETURN_ADDR = "/return"


ASYNC_CMDS = [
    # Master
    MasterControlCommand.QUIT,
    MasterControlCommand.NOTIFY,
    # Synth Def load SynthDefs
    SynthDefinitionCommand.RECV,
    SynthDefinitionCommand.LOAD,
    SynthDefinitionCommand.LOAD_DIR,
    # Buffer Commands
    BufferCommand.ALLOC,
    BufferCommand.ALLOC_READ,
    BufferCommand.ALLOC_READ_CHANNEL,
    BufferCommand.READ,
    BufferCommand.READ_CHANNEL,
    BufferCommand.WRITE,
    BufferCommand.FREE,
    BufferCommand.ZERO,
    BufferCommand.GEN,
    BufferCommand.CLOSE,
]

CMD_PAIRS = {
    # Master
    MasterControlCommand.STATUS: MasterControlReply.STATUS_REPLY,
    MasterControlCommand.SYNC: MasterControlReply.SYNCED,
    MasterControlCommand.VERSION: MasterControlReply.VERSION_REPLY,
    # Synth Commands
    SynthCommand.S_GET: NodeCommand.SET,
    SynthCommand.S_GETN: NodeCommand.SETN,
    # Group Commands
    GroupCommand.QUERY_TREE: GroupReply.QUERY_TREE_REPLY,
    # Node Commands
    NodeCommand.QUERY: NodeReply.INFO,
    # Buffer Commands
    BufferCommand.QUERY: BufferReply.INFO,
    BufferCommand.GET: BufferCommand.SET,
    BufferCommand.GETN: BufferCommand.SETN,
    # Control Bus Commands
    ControlBusCommand.GET: ControlBusCommand.SET,
    ControlBusCommand.GETN: ControlBusCommand.SETN,
}

LOCALHOST = "127.0.0.1"

SC3NB_SERVER_CLIENT_ID = 1
SC3NB_DEFAULT_PORT = 57130
SCSYNTH_DEFAULT_PORT = 57110
SC3_SERVER_NAME = "scsynth"

RESOURCES_SYNTH_DEFS = resources.__file__[: -len("__init__.py")]


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


class ServerOptions:
    """Options for the SuperCollider audio server

    This allows the encapsulation and handling of the command line server options.
    """

    def __init__(
        self,
        udp_port: int = SCSYNTH_DEFAULT_PORT,
        max_logins: int = 5,
        num_input_buses: int = 2,
        num_output_buses: int = 2,
        num_audio_buses: int = 1024,
        num_control_buses: int = 4096,
        num_sample_buffers: int = 1024,
        publish_rendezvous: bool = False,
        block_size: Optional[int] = None,
        hardware_buffer_size: Optional[int] = None,
        hardware_sample_size: Optional[int] = None,
        hardware_input_device: Optional[str] = None,
        hardware_output_device: Optional[str] = None,
        other_options: Optional[Sequence[str]] = None,
    ):
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
        self.num_input_buses = num_input_buses
        self.args += ["-i", f"{self.num_input_buses}"]
        self.num_output_buses = num_output_buses
        self.args += ["-o", f"{self.num_output_buses}"]
        if num_audio_buses < num_input_buses + num_output_buses:
            raise ValueError(
                f"You need at least {num_input_buses + num_output_buses} audio buses"
            )
        self.num_audio_buses = num_audio_buses
        self.args += ["-a", f"{self.num_audio_buses}"]

        self.num_control_buses = num_control_buses
        self.args += ["-c", f"{self.num_control_buses}"]

        self.num_sample_buffers = num_sample_buffers
        self.args += ["-b", f"{self.num_sample_buffers}"]

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
            self.args += [
                "-H",
                f"{self.hardware_input_device} {self.hardware_output_device}".strip(),
            ]

        # misc. options
        self.other_options = other_options
        if self.other_options:
            self.args += self.other_options

    @property
    def first_private_bus(self) -> int:
        """The first audio bus after input and output buses"""
        return self.num_output_buses + self.num_input_buses

    @property
    def num_private_buses(self) -> int:
        """Number of audio buses besides input and output buses"""
        return self.num_audio_buses - (self.num_output_buses + self.num_input_buses)

    def __repr__(self):
        return f"<ServerOptions {self.args}>"


class IDBlockAllocator:
    """Allows allocating blocks of ids / indexes"""

    def __init__(self, num_ids, offset):
        self._offset = offset
        self._free_ids = [i + offset for i in range(num_ids)]

    def allocate(self, num: int = 1) -> Sequence[int]:
        """Allocate the next free ids

        Returns
        -------
        int
            free id

        Raises
        ------
        RuntimeError
            When out of free ids or not enough ids are in order.
        """
        num_collected_ids = 1
        first_idx = 0
        idx = 0
        while num_collected_ids != num:
            if len(self._free_ids[first_idx:]) < num:
                raise RuntimeError(f"Cannot allocate {num} ids.")
            num_collected_ids = 1
            for idx in range(1, len(self._free_ids[first_idx:])):
                prev_id = self._free_ids[first_idx + idx - 1]
                next_id = self._free_ids[first_idx + idx]
                if abs(prev_id - next_id) > 1:
                    # difference between ids is too large
                    first_idx += idx
                    break
                num_collected_ids += 1
                if num_collected_ids == num:
                    break
        ids = self._free_ids[first_idx : first_idx + idx + 1]
        del self._free_ids[first_idx : first_idx + idx + 1]
        return ids

    def free_ids(self, ids: Sequence[int]) -> None:
        """Mark ids as free again.

        Parameters
        ----------
        ids : sequence of int
            ids that are not used anymore.
        """
        for free_id in ids:
            self._free_ids.insert(free_id - self._offset, free_id)


class SCServer(OSCCommunication):
    """SuperCollider audio server representaion."""

    def __init__(self, options: Optional[ServerOptions] = None):
        # process
        if options is None:
            self.options = ServerOptions()
            _LOGGER.debug("Using default server options %s", self.options)
        else:
            self.options = options
            _LOGGER.debug("Using custom server options %s", self.options)

        super().__init__(
            server_ip=LOCALHOST,
            server_port=SC3NB_DEFAULT_PORT,
            default_receiver_ip=LOCALHOST,
            default_receiver_port=self.options.udp_port,
        )

        # init msg queues
        self.add_msg_pairs(CMD_PAIRS)

        # /return messages from sclang callback
        self.returns = MessageQueue(ReplyAddress.RETURN_ADDR, preprocess_return)
        self.add_msg_queue(self.returns)

        # /done messages must be seperated
        self.dones = MessageQueueCollection(
            address=ReplyAddress.DONE_ADDR, sub_addrs=ASYNC_CMDS
        )
        self.add_msg_queue_collection(self.dones)

        self.fails = MessageQueueCollection(address=ReplyAddress.FAIL_ADDR)
        self.add_msg_queue_collection(self.fails)

        # set logging handlers
        self._osc_server.dispatcher.map(
            ReplyAddress.FAIL_ADDR, self._warn_fail, needs_reply_address=True
        )
        self._osc_server.dispatcher.map(
            ReplyAddress.WILDCARD_ADDR, self._log_message, needs_reply_address=True
        )

        self.buffer_id_allocator: Optional[IDBlockAllocator] = None
        self.control_bus_id_allocator: Optional[IDBlockAllocator] = None
        self.audio_bus_id_allocator: Optional[IDBlockAllocator] = None

        # node managing
        self.nodes: WeakValueDictionary[int, Node] = WeakValueDictionary()

        self._root_node = Group(0, group=0, new=False, target=0, server=self)
        self._default_groups: Dict[int, Group] = {}
        self._is_local: bool = False

        self._output_bus = Bus(
            rate=BusRate.AUDIO,
            num_channels=self.options.num_output_buses,
            index=0,
            server=self,
        )
        self._input_bus = Bus(
            rate=BusRate.AUDIO,
            num_channels=self.options.num_input_buses,
            index=self.options.num_output_buses,
            server=self,
        )

        # counter for nextNodeID
        self._num_node_ids: int = 0

        self.process: Optional[Process] = None
        self._programm_name = SC3_SERVER_NAME

        self._client_id: int = SC3NB_SERVER_CLIENT_ID
        self._scsynth_address = LOCALHOST
        self._scsynth_port = self.options.udp_port
        self._max_logins = self.options.max_logins

        self._server_running: bool = False
        self._has_booted: bool = False

        self.latency: float = 0.0

    def boot(
        self,
        scsynth_path: Optional[str] = None,
        timeout: float = 3,
        console_logging: bool = True,
        with_blip: bool = True,
        kill_others: bool = True,
        allowed_parents: Sequence[str] = ALLOWED_PARENTS,
    ):
        """Start the Server process.

        Parameters
        ----------
        scsynth_path : str, optional
            Path of scscynth executable, by default None
        timeout : float, optional
            Timeout for starting the executable, by default 3
        console_logging : bool, optional
            If True write process output to console, by default True
        with_blip : bool, optional
            make a sound when booted, by default True
        kill_others : bool
            kill other SuperCollider server processes.
        allowed_parents : Sequence[str], optional
            Names of parents that are allowed for other instances of
            sclang/scsynth processes that won't be killed, by default ALLOWED_PARENTS

        Raises
        ------
        ValueError
            If UDP port specified in options is already used
        ProcessTimeout
            If the process fails to start.
        """
        if self._has_booted:
            warnings.warn("already booted")
            return
        print("Booting SuperCollider Server...")
        self._is_local = True
        self._scsynth_address = LOCALHOST
        self._scsynth_port = self.options.udp_port
        self.process = Process(
            executable=self._programm_name,
            args=self.options.args,
            exec_path=scsynth_path,
            console_logging=console_logging,
            kill_others=kill_others,
            allowed_parents=allowed_parents,
        )
        try:
            self.process.read(expect="SuperCollider 3 server ready.", timeout=timeout)
        except ProcessTimeout as process_timeout:
            if "Exception in World_OpenUDP" in process_timeout.output:
                # ToDo check if string is correct in Linux
                self.process.kill()
                self.process = None
                print("SuperCollider Server port already used.")
                if self.options.udp_port != SCSYNTH_DEFAULT_PORT:
                    raise ValueError(
                        f"The specified UDP port {self.options.udp_port} is already used"
                    )
                else:
                    print("Trying to connect.")
                    self.remote(
                        self._scsynth_address, self._scsynth_port, with_blip=with_blip
                    )
            else:
                print("Failed booting SuperCollider Server.")
                raise process_timeout
        else:
            self.init(with_blip)
            self._has_booted = True

    def init(self, with_blip: bool = True):
        """Initialize the server.

        This adds allocators, loads SynthDefs, send default Groups etc.

        Parameters
        ----------
        with_blip : bool, optional
            make a sound when initialized, by default True
        """
        # notify the supercollider server about us
        self.add_receiver(
            self._programm_name, self._scsynth_address, self._scsynth_port
        )
        self.notify()

        # init allocators
        buffers_per_user = int(self.options.num_sample_buffers / self.max_logins)
        buffer_id_offset = self.client_id * buffers_per_user
        self.buffer_id_allocator = IDBlockAllocator(buffers_per_user, buffer_id_offset)

        audio_buses_per_user = int(self.options.num_private_buses / self.max_logins)
        audio_bus_id_offset = (
            self.client_id * audio_buses_per_user + self.options.first_private_bus
        )
        self.audio_bus_id_allocator = IDBlockAllocator(
            audio_buses_per_user, audio_bus_id_offset
        )

        control_buses_per_user = int(self.options.num_control_buses / self.max_logins)
        control_bus_id_offset = self.client_id * control_buses_per_user
        self.control_bus_id_allocator = IDBlockAllocator(
            control_buses_per_user, control_bus_id_offset
        )

        # load synthdefs of sc3nb
        self.load_synthdefs()

        # create default groups
        self.send_default_groups()

        self.sync()
        if with_blip:
            self.blip()

        print("Done.")

    def bundler(self, timestamp=0, msg=None, msg_args=None, send_on_exit=True):
        """Generate a Bundler with added server latency.

        This allows the user to easly add messages/bundles and send it.

        Parameters
        ----------
        timestamp : int
            Time at which bundle content should be executed.
            This servers latency will be added upon this.
            If timestamp <= 1e6 it is added to time.time().
        msg_addr : str
            SuperCollider address.
        msg_args : list, optional
            List of arguments to add to message.
             (Default value = None)

        Returns
        -------
        Bundler
            bundler for OSC bundling.
        """
        return super().bundler(
            timestamp=timestamp + self.latency,
            msg=msg,
            msg_args=msg_args,
            send_on_exit=send_on_exit,
        )

    def blip(self) -> None:
        """Make a blip sound"""
        with self.bundler(0.1) as bundler:
            bundler.add(
                0.1, "/s_new", ["s1", -1, 0, 0, "freq", 500, "dur", 0.1, "num", 1]
            )
            bundler.add(
                0.3, "/s_new", ["s2", -1, 0, 0, "freq", 1000, "amp", 0.05, "num", 2]
            )
            bundler.add(0.4, "/n_free", [-1])

    def remote(self, address: str, port: int, with_blip: bool = True) -> None:
        """Connect to remote Server

        Parameters
        ----------
        address : str
            address of remote server
        port : int
            port of remote server
        with_blip : bool, optional
            make a sound when initialized, by default True
        """
        self._is_local = False
        self._scsynth_address = address
        self._scsynth_port = port
        self.init(with_blip=with_blip)
        self._has_booted = True

    def reboot(self) -> None:
        """Reboot this server

        Raises
        ------
        RuntimeError
            If this server is remote and can't be restarted.
        """
        if not self.is_local:
            raise RuntimeError("Can't reboot a remote Server")
        self.quit()
        self.boot()

    def ping(self):
        """Ping the server."""
        raise NotImplementedError

    # messages
    def quit(self) -> None:
        """Quits and tries to kill the server."""
        try:
            self.send(build_message(MasterControlCommand.QUIT))
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
        msg = build_message(MasterControlCommand.SYNC, sync_id)
        return sync_id == self.send(msg, timeout=timeout)

    def send_synthdef(self, synthdef_bytes: bytes, wait: bool = True):
        """Send a SynthDef as bytes.

        Parameters
        ----------
        synthdef_bytes : bytes
            SynthDef bytes
        wait : bool
            If True wait for server reply.
        """
        self.msg(SynthDefinitionCommand.RECV, synthdef_bytes, await_reply=wait)

    def load_synthdef(self, synthdef_path: str, wait: bool = True):
        """Load SynthDef file at path.

        Parameters
        ----------
        synthdef_path : str
            Path with the SynthDefs
        wait : bool
            If True wait for server reply.
        """
        self.msg(SynthDefinitionCommand.LOAD, synthdef_path, await_reply=wait)

    def load_synthdefs(
        self,
        directory: Optional[str] = None,
        completion_msg: bytes = None,
        wait: bool = True,
    ) -> None:
        """Load all SynthDefs from directory.

        Parameters
        ----------
        directory : str, optional
            directory with SynthDefs, by default sc3nb default SynthDefs
        completion_msg : bytes, optional
            Message to be executed by the server when loaded, by default None
        wait : bool, optional
            If True wait for server reply, by default True
        """
        if directory is None:
            directory = RESOURCES_SYNTH_DEFS
        args: List[Union[str, bytes]] = [directory]
        if completion_msg is not None:
            args.append(completion_msg)
        self.msg(SynthDefinitionCommand.LOAD_DIR, args, await_reply=wait)

    def notify(
        self,
        receive_notifications: bool = True,
        client_id: Optional[int] = None,
        timeout: float = 1.0,
    ) -> None:
        """Notify the server about this client.

        This provides the client id and max logins info needed for default groups.

        Parameters
        ----------
        receive_notifications : bool, optional
            Flag for receiving node notification from server, by default True
        client_id : int, optional
            Propose a client id, by default None
        timeout : float, optional
            Timeout for server reply, by default 1.0

        Raises
        ------
        RuntimeError
            If server has too many users.
        OSCCommunicationError
            If OSC communication fails.
        """
        flag = 1 if receive_notifications else 0
        client_id = client_id if client_id else self._client_id
        msg = build_message(
            MasterControlCommand.NOTIFY, [flag, client_id]
        )  # flag, clientID
        try:
            return_val = self.send(msg, timeout=timeout)
        except OSCCommunicationError as error:
            errors = self._get_errors_for_address(msg.address)
            if len(errors) > 0:
                last_error_value = errors[-1]
                if isinstance(last_error_value, tuple):
                    message, *rest = last_error_value
                else:
                    message = last_error_value
                    rest = None

                if "already registered" in message:
                    self._client_id = rest[0]
                    return  # only send client_id but not max logins
                elif "too many users" in message:
                    raise RuntimeError(
                        "scsynth has too many users. Can't notify."
                    ) from error
                elif "not registered" in message:
                    return  # ignore when we are already not notified anymore.
            raise error
        else:
            if receive_notifications:
                self._client_id, self._max_logins = return_val

    def _get_errors_for_address(self, address: str):
        error_values = []
        if address in self.fails:
            while True:
                try:
                    error_values.append(self.fails.msg_queues[address].get(timeout=0))
                except Empty:
                    break
        return error_values

    def free_all(self, root: bool = True) -> None:
        """Free all node ids.

        Parameters
        ----------
        root : bool, optional
            If False free only the default group of this client, by default True
        """
        if root:
            group = self._root_node
        else:
            group = self.default_group
        group.free_all()
        self.msg(MasterControlCommand.CLEAR_SCHED)
        if root:
            self.send_default_groups()
        else:
            self.default_group.new()
        self.sync()

    def send_default_groups(self) -> None:
        """Send the default groups for all clients."""
        client_ids = range(self._max_logins)

        def create_default_group(client_id):
            return Group(nodeid=2 ** 26 * client_id + 1, target=0, server=self).new()

        self._default_groups = {
            client: create_default_group(client) for client in client_ids
        }

    def allocate_node_id(self) -> int:
        """Get a node id.

        Returns
        -------
        int
            node id
        """
        self._num_node_ids += 1
        node_id = self._num_node_ids + 10000 * (self._client_id + 1)
        return node_id

    def allocate_buffer_id(self, num: int = 1) -> Sequence[int]:
        """Get the next free buffer id.

        Returns
        -------
        int
            buffer id
        """
        return self.buffer_id_allocator.allocate(num)

    def allocate_control_bus_idx(self, num: int = 1) -> Sequence[int]:
        """Get the next free bus id.

        Returns
        -------
        int
            bus id
        """
        return self.control_bus_id_allocator.allocate(num)

    def allocate_audio_bus_idx(self, num: int = 1) -> Sequence[int]:
        """Get the next free bus id.

        Returns
        -------
        int
            bus id
        """
        return self.audio_bus_id_allocator.allocate(num)

    @property
    def client_id(self):
        """The client id for this server"""
        return self._client_id

    @property
    def max_logins(self):
        """Maximum number of possible logins at server"""
        return self._max_logins

    @property
    def default_group(self):
        """This clients default group"""
        return self._default_groups[self._client_id]

    @property
    def input_bus(self) -> Bus:
        """This servers input Bus"""
        return self._input_bus

    @property
    def output_bus(self) -> Bus:
        """This servers output Bus"""
        return self._output_bus

    # Volume Class in Supercollider. Controls Filter Synth
    @property
    def volume(self):
        """Server volume in [0, 1]"""
        raise NotImplementedError

    @volume.setter
    def volume(self):
        raise NotImplementedError

    def mute(self):
        """Set volume to 0"""
        raise NotImplementedError

    def unmute(self):
        """Set volume back to volume prior to muting"""
        raise NotImplementedError

    # Information and debugging
    def version(self) -> ServerVersion:
        """Server version information"""
        msg = build_message(MasterControlCommand.VERSION)
        return ServerVersion._make(self.send(msg))

    def status(self) -> ServerStatus:
        """Server status information"""
        msg = build_message(MasterControlCommand.STATUS)
        return ServerStatus._make(self.send(msg)[1:])

    def dump_osc(self, level: int = 1) -> None:
        """Enable dumping incoming OSC messages at the server process

        Parameters
        ----------
        level : int, optional
            Verbosity code, by default 1
            0	turn dumping OFF.
            1	print the parsed contents of the message.
            2	print the contents in hexadecimal.
            3	print both the parsed and hexadecimal representations.
        """
        msg = build_message(MasterControlCommand.DUMP_OSC, [level])
        self.send(msg)

    def dump_tree(self, controls: bool = True, return_tree=False) -> Optional[str]:
        """Server process prints out current nodes

        Parameters
        ----------
        controls : bool, optional
            If True include control values, by default True
        return_tree : bool, optional
            If True return output as string, by default False

        Returns
        -------
        str
            If return_tree this is the node tree string.
        """
        self.process.read()
        msg = build_message(GroupCommand.DUMP_TREE, [0, 1 if controls else 0])
        self.send(msg)
        node_tree = self.process.read(expect="NODE TREE")
        print(node_tree)
        if return_tree:
            return node_tree

    def query_all_nodes(self, include_controls: bool = True) -> NodeTree:
        """Query all nodes at the server and return a NodeTree

        Parameters
        ----------
        include_controls : bool, optional
            If True include control values, by default True

        Returns
        -------
        NodeTree
            object containing all the nodes.
        """
        return self._root_node.query_tree(include_controls=include_controls)

    @property
    def peak_cpu(self) -> float:
        """Peak cpu usage of server process"""
        return self.status().peak_cpu

    @property
    def avg_cpu(self) -> float:
        """Average cpu usage of server process"""
        return self.status().peak_cpu

    @property
    def sample_rate(self) -> float:
        """Nominal sample rate of server process"""
        return self.status().nominal_sr

    @property
    def actual_sample_rate(self) -> float:
        """Actual sample rate of server process"""
        return self.status().actual_sr

    @property
    def num_synths(self) -> int:
        """Number of Synths in server tree"""
        return self.status().num_synths

    @property
    def num_groups(self) -> int:
        """Number of Groups in server tree"""
        return self.status().num_groups

    @property
    def num_ugens(self) -> int:
        """Number of UGens in server tree"""
        return self.status().num_ugens

    @property
    def num_synthdefs(self) -> int:
        """Number of SynthDefs known by server"""
        return self.status().num_synthdefs

    @property
    def addr(self) -> Tuple[str, int]:
        """Address (ip, port) of server"""
        return (self._scsynth_address, self._scsynth_port)

    @property
    def has_booted(self) -> bool:
        """If the server is booted"""
        return self._has_booted

    @property
    def server_running(self) -> int:
        """If the server is running"""
        return self._server_running

    @property
    def unresponsive(self) -> bool:
        """If the server process is unresponsive"""
        try:
            self.status()
        except OSCCommunicationError:
            return True
        else:
            return False

    @property
    def is_local(self) -> bool:
        """If the server process is local"""
        return self._is_local

    @property
    def pid(self):
        """The process id of the local server process"""
        if self.is_local:
            return self.process.popen.pid
        else:
            warnings.warn("Server is not local or not booted.")

    def _log_message(self, sender, *args):
        if len(str(args)) > 55:
            args_str = str(args)[:55] + ".."
        else:
            args_str = str(args)
        _LOGGER.info(
            "osc msg received from %s: %s", self._check_sender(sender), args_str
        )

    def _warn_fail(self, sender, *args):
        warnings.warn(f"Error from {self._check_sender(sender)}: {args}")
