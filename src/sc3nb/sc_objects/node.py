"""Implements Node and subclasses Synth and Group."""

import logging
import warnings
from abc import ABC, abstractmethod
from enum import Enum, unique
from functools import reduce
from operator import iconcat
from threading import Event, RLock
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    Union,
)

import sc3nb
from sc3nb.osc.osc_communication import OSCCommunicationError, OSCMessage
from sc3nb.sc_objects.synthdef import SynthDef

if TYPE_CHECKING:
    from sc3nb.sc_objects.bus import Bus
    from sc3nb.sc_objects.server import SCServer
    from sc3nb.sclang import SynthArgument

_LOGGER = logging.getLogger(__name__)


@unique
class GroupReply(str, Enum):
    """Replies of Group Commands"""

    QUERY_TREE_REPLY = "/g_queryTree.reply"


@unique
class GroupCommand(str, Enum):
    """OSC Commands for Groups"""

    QUERY_TREE = "/g_queryTree"
    DUMP_TREE = "/g_dumpTree"
    DEEP_FREE = "/g_deepFree"
    FREE_ALL = "/g_freeAll"
    TAIL = "/g_tail"
    HEAD = "/g_head"
    G_NEW = "/g_new"
    P_NEW = "/p_new"


@unique
class SynthCommand(str, Enum):
    """OSC Commands for Synths"""

    NEW = "/s_new"
    S_GET = "/s_get"
    S_GETN = "/s_getn"


@unique
class NodeReply(str, Enum):
    """Replies of Node Commands"""

    INFO = "/n_info"


@unique
class NodeCommand(str, Enum):
    """OSC Commands for Nodes"""

    ORDER = "/n_order"
    TRACE = "/n_trace"
    QUERY = "/n_query"
    MAP = "/n_map"
    MAPN = "/n_mapn"
    MAPA = "/n_mapa"
    MAPAN = "/n_mapan"
    FILL = "/n_fill"
    SET = "/n_set"
    SETN = "/n_setn"
    RUN = "/n_run"
    FREE = "/n_free"


@unique
class AddAction(Enum):
    """AddAction of SuperCollider nodes.

    This Enum contains the codes for the different ways to add a node.
    """

    TO_HEAD = 0  # (the default) add at the head of the group specified by target
    TO_TAIL = 1  # add at the tail of the group specified by target
    BEFORE = 2  # add immediately before target in its server's node order
    AFTER = 3  # add immediately after target in its server's node order
    REPLACE = 4  # replace target and take its place in its server's node order
    # Note: A Synth is not a valid target for \addToHead and \addToTail.


class SynthInfo(NamedTuple):
    """Information about the Synth from /n_info"""

    nodeid: int
    group: int
    prev_nodeid: int
    next_nodeid: int


class GroupInfo(NamedTuple):
    """Information about the Group from /n_info"""

    nodeid: int
    group: int
    prev_nodeid: int
    next_nodeid: int
    head: int
    tail: int


class Node(ABC):
    """Representation of a Node on SuperCollider."""

    def __new__(
        cls,
        *args: Any,
        nodeid: Optional[int] = None,
        server: Optional["SCServer"] = None,
        **kwargs: Any,
    ) -> "Node":
        if nodeid is not None:
            if server is None:
                server = sc3nb.SC.get_default().server
            try:
                node = server.nodes[nodeid]
                if node is not None:
                    if node.freed and not node.is_playing:
                        _LOGGER.debug(
                            "Removing %s(%s) from %s",
                            type(node).__name__,
                            node.nodeid,
                            repr(server),
                        )
                        del server.nodes[nodeid]
                    # check here if nodes types are compatible
                    elif isinstance(node, cls):
                        _LOGGER.debug(
                            "Returned %s(%s) from %s",
                            type(node).__name__,
                            node.nodeid,
                            repr(server),
                        )
                        return node
                    else:
                        raise RuntimeError(
                            f"Tried to get {node} from {server}"
                            f" as {cls.__name__} but type is {type(node).__name__}"
                        )
            except KeyError:
                pass
        _LOGGER.debug("%s(%s) not in Server (%s)", cls.__name__, nodeid, server)
        return super().__new__(cls)

    @abstractmethod
    def __init__(
        self,
        *,
        nodeid: Optional[int] = None,
        add_action: Optional[Union[AddAction, int]] = None,
        target: Optional[Union["Node", int]] = None,
        server: Optional["SCServer"] = None,
    ) -> None:
        """Create a new Node

        Parameters
        ----------
        nodeid : int or None
            This Nodes node id or None
        add_action : AddAction or corresponding int, optional
            This Nodes AddAction when created in Server, by default None
        target : Node or int or None, optional
            This Nodes AddActions target, by default None
        server : SCServer, optional
            The Server for this Node,
            by default use the SC default server
        """
        self._server = server or sc3nb.SC.get_default().server
        if nodeid in self._server.nodes:
            raise RuntimeError("The __init__ of Node should not be called twice")

        self._state_lock = RLock()
        self._free_event = Event()
        self._on_free_callback = None
        self._started = False
        self._freed = False

        self._nodeid = (
            nodeid if nodeid is not None else self._server.node_ids.allocate(1)[0]
        )
        self._group = None

        self._target_id = Node._get_nodeid(target) if target is not None else None
        if add_action is not None:
            self._add_action = AddAction(add_action)
        else:
            self._add_action = AddAction.TO_HEAD

        self._set_node_attrs(target, add_action)

        # only with node watcher
        self._is_playing = None
        self._is_running = None

        # this is state that we cannot really be sure of
        self._current_controls = {}

        _LOGGER.debug(
            "Adding new %s(%s) to %s", type(self).__name__, self._nodeid, self._server
        )
        self._server.nodes[self._nodeid] = self

    @abstractmethod
    def new(
        self,
        *args,
        add_action: Optional[Union[AddAction, int]] = None,
        target: Optional[Union["Node", int]] = None,
        return_msg: bool = False,
        **kwargs,
    ) -> Union["Node", OSCMessage]:
        """Create a new Node

        Parameters
        ----------
        add_action : AddAction or int, optional
            Where the Node should be added, by default AddAction.TO_HEAD (0)
        target : Node or int, optional
            AddAction target, if None it will be the default group of the server
        """
        with self._state_lock:
            self._started = True
            self._freed = False
            self._free_event.clear()
            self._is_playing = None
            self._is_running = None
            self._set_node_attrs(target=target, add_action=add_action)

    def _get_status_repr(self) -> str:
        status = ""
        if self.started and not self.is_playing:
            status = "s"
        if self.is_playing:
            running_symbol = "~" if self.is_running else "-"
            status = running_symbol
        if self.freed:
            status = "f"
        return status

    def _set_node_attrs(
        self,
        target: Optional[Union["Node", int]] = None,
        add_action: Optional[Union[AddAction, int]] = None,
    ) -> None:
        """Derive Node group from addaction and target

        Parameters
        ----------
        target : int or Node
            Target nodeid or Target Node of this Node's AddAction
        add_action : AddAction
            AddAction of this Node, default AddAction.TO_HEAD (0)
        """
        with self._state_lock:
            _LOGGER.debug(
                "Node attrs before setting: nodeid %s, group %s, add_action %s, target %s",
                self._nodeid,
                self._group,
                self._add_action,
                self._target_id,
            )
            # get target id
            if target is not None:
                self._target_id = Node._get_nodeid(target)
            else:
                if self._target_id is None:
                    self._target_id = self.server.default_group.nodeid

            # get add action
            if add_action is None:
                self._add_action = AddAction.TO_HEAD
            elif isinstance(add_action, AddAction):
                self._add_action = add_action
            else:
                self._add_action = AddAction(add_action)

            # derive group
            if self._add_action in [AddAction.TO_HEAD, AddAction.TO_TAIL]:
                self._group = self._target_id
            elif self._group is None:  # AddAction BEFORE, AFTER or REPLACE
                if isinstance(target, Node):
                    self._group = target.group
                elif target in self._server.nodes:
                    target_node = self._server.nodes[self._target_id]
                    if target_node:
                        self._group = target_node.group
                else:
                    _LOGGER.warning(
                        "Could not derive group of Node, assuming default group"
                    )
                    self._group = self._server.default_group.nodeid
            _LOGGER.debug(
                "Node attrs after setting: nodeid %s, group %s, add_action %s, target %s",
                self._nodeid,
                self._group,
                self._add_action,
                self._target_id,
            )

    @property
    def nodeid(self) -> int:
        """Identifier of node."""
        return self._nodeid

    @property
    def group(self) -> Optional[int]:
        """Identifier of this nodes group."""
        return self._group

    @property
    def server(self) -> "SCServer":
        """The server on which this node is located."""
        return self._server

    @property
    def is_playing(self) -> Optional[bool]:
        """True if this node is playing. None if unkown."""
        return self._is_playing

    @property
    def is_running(self) -> Optional[bool]:
        """True if this node is running. None if unkown."""
        return self._is_running

    @property
    def freed(self) -> bool:
        """True if free was called on this node.

        This is reseted when receiving a /n_go notification
        """
        return self._freed

    @property
    def started(self) -> bool:
        """True if new was called on this node.

        This is reseted when receiving a /n_end notification
        """
        return self._started

    def free(self, return_msg: bool = False) -> Union["Node", OSCMessage]:
        """Free the node with /n_free.

        This will set is_running and is_playing to false.
        Even when the message is returned to mimic the behavior of the SuperCollider Node
        See https://doc.sccode.org/Classes/Node.html#-freeMsg

        Returns
        -------
        Node or OSCMessage
            self for chaining or OSCMessage when return_msg=True
        """
        with self._state_lock:
            self._freed = True
        msg = OSCMessage(NodeCommand.FREE, [self.nodeid])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True)
        return self

    def run(
        self, on: bool = True, return_msg: bool = False
    ) -> Union["Node", OSCMessage]:
        """Turn node on or off with /n_run.

        Parameters
        ----------
        on : bool
            True for on, False for off, by default True

        Returns
        -------
        Node or OSCMessage
            self for chaining or OSCMessage when return_msg=True
        """
        msg = OSCMessage(NodeCommand.RUN, [self.nodeid, 1 if on else 1])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True)
        return self

    def set(
        self,
        argument: Union[str, Dict, List],
        *values: Any,
        return_msg: bool = False,
    ) -> Union["Node", OSCMessage]:
        """Set a control value(s) of the node with n_set.

        Parameters
        ----------
        argument : str | dict | list
            if string: name of control argument
            if dict: dict with argument, value pairs
            if list: use list as message content
        value : any, optional
            only used if argument is string, by default None

        Examples
        --------

        >>> synth.set("freq", 400)
        >>> synth.set({"dur": 1, "freq": 400})
        >>> synth.set(["dur", 1, "freq", 400])

        """
        # update cached current_control values
        with self._state_lock:
            msg_params: List[Any] = [self.nodeid]
            if isinstance(argument, dict):
                for arg, val in argument.items():
                    msg_params.append(arg)
                    msg_params.append(val)
                    self._update_control(arg, val)
            elif isinstance(argument, list):
                for arg_idx, arg in enumerate(argument):
                    if isinstance(arg, str):
                        self._update_control(arg, argument[arg_idx + 1])
                msg_params.extend(argument)
            else:
                if len(values) == 1:
                    self._update_control(argument, values[0])
                else:
                    self._update_control(argument, values)
                msg_params.extend([argument] + list(values))
        msg = OSCMessage(NodeCommand.SET, msg_params)
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True)
        return self

    def _update_control(self, control: str, value: Any) -> None:
        with self._state_lock:
            try:
                val = object.__getattribute__(self, control)
            except AttributeError:
                pass
            else:
                warnings.warn(
                    f"attribute {control}={val} is deleted and recognized as Node Parameter now"
                )
                delattr(self, control)
            if not control.startswith("t_"):
                self._current_controls[control] = value

    def _update_controls(self, controls: Optional[Dict[str, Any]] = None) -> None:
        with self._state_lock:
            if controls is not None:
                for arg, val in controls.items():
                    self._update_control(arg, val)

    def fill(
        self,
        control: Union[str, int],
        num_controls: int,
        value: Any,
        return_msg: bool = False,
    ) -> Union["Node", OSCMessage]:
        """Fill ranges of control values with n_fill.

        Parameters
        ----------
        control : int or string
            control index or name
        num_controls : int
            number of control values to fill
        value : float or int
            value to set
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        OSCMessage
            if return_msg else self
        """
        msg = OSCMessage(NodeCommand.FILL, [self.nodeid, control, num_controls, value])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True)
        return self

    def map(
        self, control: Union[str, int], bus: "Bus", return_msg: bool = False
    ) -> Union["Node", OSCMessage]:
        """Map a node's control to read from a bus using /n_map or /n_mapa.

        Parameters
        ----------
        control : int or string
            control index or name
        bus : Bus
            control/audio bus
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        OSCMessage
            if return_msg else self
        """
        msg_params = [self.nodeid, control, bus.idxs[0]]
        if bus.num_channels > 1:
            map_command = NodeCommand.MAPAN if bus.is_audio_bus() else NodeCommand.MAPN
            msg_params.append(bus.num_channels)
        else:
            map_command = NodeCommand.MAPA if bus.is_audio_bus() else NodeCommand.MAP
        msg = OSCMessage(map_command, msg_params)
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True)
        return self

    def release(
        self, release_time: Optional[float] = None, return_msg: bool = False
    ) -> Union["Node", OSCMessage]:
        """Set gate as specified.

        https://doc.sccode.org/Classes/Node.html#-release

        Parameters
        ----------
        release_time : float, optional
            amount of time in seconds during which the node will release.
            If set to a value <= 0, the synth will release immediately.
            If None using its Envs normal release stage(s)
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        OSCMessage
            if return_msg else self
        """
        if release_time is not None:
            release_time = 1 if release_time <= 0 else -1 * (release_time + 1)
        else:
            release_time = 0

        msg = OSCMessage(NodeCommand.SET, [self.nodeid, "gate", release_time])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True)
        return self

    def query(self) -> Union[SynthInfo, GroupInfo]:
        """Sends an n_query message to the server.

        The answer is send to all clients who have registered via the /notify command.
        Content of answer:

        node ID
        the node's parent group ID
        previous node ID, -1 if no previous node.
        next node ID, -1 if no next node.
        1 if the node is a group, 0 if it is a synth

        if the node is a group:
            ID of the head node, -1 if there is no head node.
            ID of the tail node, -1 if there is no tail node.

        Returns
        -------
        SynthInfo or GroupInfo
            n_info answer. See above for content description
        """
        msg = OSCMessage(NodeCommand.QUERY, [self.nodeid])
        result = self.server.send(msg, bundle=False)
        return self._parse_info(*result)

    def trace(self, return_msg: bool = False) -> Union["Node", OSCMessage]:
        """Trace a node.

        Print out values of the inputs and outputs for one control period.
        If node is a group then print the node IDs and names of each node.

        Parameters
        ----------
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        Node or OSCMessage
            if return_msg else self
        """
        msg = OSCMessage(NodeCommand.TRACE, [self.nodeid])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True)
        return self

    def move(
        self, add_action: AddAction, another_node: "Node", return_msg: bool = False
    ) -> Union["Node", OSCMessage]:
        """Move this node

        Parameters
        ----------
        add_action : AddAction [TO_HEAD, TO_TAIL, AFTER, BEFORE]
            What add action should be done.
        another_node : Node
            The node which is the target of the add action
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        Node or OSCMessage
            if return_msg this will be the OSCMessage, else self

        Raises
        ------
        ValueError
            If a wrong AddAction was provided
        """
        if add_action == AddAction.REPLACE:
            raise ValueError(
                "add_action needs to be in [TO_HEAD, TO_TAIL, AFTER, BEFORE]"
            )
        msg = OSCMessage(
            NodeCommand.ORDER, [add_action.value, another_node.nodeid, self.nodeid]
        )
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True)
        return self

    def register(self):
        """Register to be watched."""
        raise NotImplementedError("Currently all nodes are being watched on default")

    def unregister(self):
        """Unregister to stop being watched."""
        raise NotImplementedError("Currently all nodes are being watched on default")

    def on_free(self, func):
        """Callback that is executed when this Synth is freed"""
        self._on_free_callback = func

    def wait(self, timeout: Optional[float] = None) -> None:
        """Wait until this Node is freed

        Raises
        ------
        TimeoutError
            If timeout was provided and wait timed out.
        """
        # TODO check if self._server is in bundling mode,
        # This should probably fail if used inside of Bundler
        if not self._free_event.wait(timeout=timeout):
            raise TimeoutError("Timed out waiting for synth.")

    def _parse_info(
        self,
        nodeid: int,
        group: int,
        prev_nodeid: int,
        next_nodeid: int,
        *rest: Sequence[int],
    ) -> Union[SynthInfo, GroupInfo]:
        assert (
            self.nodeid == nodeid
        ), "nodeids does not match self.nodeid={self.nodeid} != {nodeid}"
        if len(rest) == 1 and rest[0] == 0:  # node is synth
            return SynthInfo._make([nodeid, group, prev_nodeid, next_nodeid])
        else:
            _, head, tail = rest
            return GroupInfo._make(
                [nodeid, group, prev_nodeid, next_nodeid, head, tail]
            )

    def _handle_notification(self, kind: str, info) -> None:
        with self._state_lock:
            if kind == "/n_go":
                self._is_playing = True
                self._is_running = True
                self._started = True
                self._freed = False
            elif kind == "/n_end":
                self._is_playing = False
                self._is_running = False
                self._started = False
                self._freed = True
                self._group = None
                self._free_event.set()
                if self._on_free_callback is not None:
                    self._on_free_callback()
            elif kind == "/n_on":
                self._is_running = True
                self._freed = False
            elif kind == "/n_off":
                self._is_running = False
                self._started = False
            elif kind == "/n_move":
                node_info = self._parse_info(*info)
                self._group = node_info.group
            else:
                raise ValueError(f"Illegal notification kind '{kind}' {info}")
        _LOGGER.debug("Handled %s notification: %s", kind, info)

    def __eq__(self, other):
        return self.nodeid == other.nodeid

    @staticmethod
    def _get_nodeid(value: Union["Node", int]) -> int:
        """Get the corresponding node id

        Parameters
        ----------
        value : Node or int
            If a Node is provided it will get its nodeid
            If a int is provided it will be returned

        Returns
        -------
        int
            nodeid

        Raises
        ------
        ValueError
            When neither Node or int was provided
        """
        if isinstance(value, Node):
            nodeid = value.nodeid
        elif isinstance(value, int):
            nodeid = value
        else:
            raise ValueError("Could not get a node id")
        return nodeid


class Synth(Node):
    """Representation of a Synth on SuperCollider."""

    def __init__(
        self,
        name: Optional[str] = None,
        controls: Dict[str, Any] = None,
        *,
        nodeid: Optional[int] = None,
        new: bool = True,
        add_action: Optional[Union[AddAction, int]] = None,
        target: Optional[Union["Node", int]] = None,
        server: Optional["SCServer"] = None,
    ) -> None:
        """Create a Python representation of a SuperCollider synth.

        Parameters
        ----------
        sc : SC
            sc3nb SuperCollider instance
        name : str, optional
            name of the synth to be created, by default "default"
        controls : dict, optional
            synth control arguments, by default None
        nodeid : int, optional
            ID of the node in SuperCollider, by default sc3nb will create one.
            Can be set to an existing id to create a Python instance of a running Node.
        new : bool, optional
            True if synth should be created on the server, by default True
            Should be False if creating an instance of a running Node.
        add_action : AddAction or int, optional
            Where the Synth should be added, by default AddAction.TO_HEAD (0)
        target : Node or int, optional
            AddAction target, if None it will be the default group of the server

        Raises
        ------
        ValueError
            Raised when synth can't be found via SynthDescLib.global

        Examples
        --------

        >>> scn.Synth(sc, "s1", {"dur": 1, "freq": 400})

        """
        self._server = server or sc3nb.SC.get_default().server
        if nodeid in self._server.nodes:
            self._update_synth_state(name=name, controls=controls)
            if new:
                self.new(controls=controls, add_action=add_action, target=target)
            return

        # attention: this must be the first line. see __setattr__, __getattr__
        self._initialized = False
        super().__init__(
            nodeid=nodeid,
            add_action=add_action,
            target=target,
            server=server,
        )
        with self._state_lock:
            self._name = name or "default"
            self._synth_desc = SynthDef.get_description(self._name)
            if controls is None:
                controls = {}
            self._current_controls = controls

            self._freed = False
            self._started = False

            # attention: this must be after every attribute is set
            self._initialized = True
        if new:
            self.new(
                controls=self._current_controls,
                add_action=self._add_action,
                target=self._target_id,
            )

    def _update_synth_state(self, name: Optional[str], controls: Optional[dict]):
        _LOGGER.debug("Update Synth(%s)", self.nodeid)
        with self._state_lock:
            if name is not None:
                self._name = name
                self._synth_desc = SynthDef.get_description(name)
            self._update_controls(controls)

    @property
    def synth_desc(self) -> Optional[Dict[str, "SynthArgument"]]:
        """A Description of this Synths arguments"""
        with self._state_lock:
            if self._synth_desc is None:
                self._synth_desc = SynthDef.get_description(self._name)
        return self._synth_desc

    @property
    def name(self) -> str:
        """This Synths SynthDef name."""
        return self._name

    @property
    def current_controls(self) -> Dict[str, Any]:
        """This Synth currently cached control arguments."""
        return self._current_controls

    def new(
        self,
        controls: Optional[dict] = None,
        add_action: Optional[Union[AddAction, int]] = None,
        target: Optional[Union[Node, int]] = None,
        *,
        return_msg: bool = False,
    ) -> Union["Synth", OSCMessage]:
        """Creates the synth on the server with s_new.

        Attention: Here you create an identical synth! Same nodeID etc.
        - This will fail if there is already this nodeID on the SuperCollider server!
        """
        with self._state_lock:
            super().new(target=target, add_action=add_action)
            self._update_controls(controls)
            flatten_args = reduce(iconcat, self._current_controls.items(), [])

        msg = OSCMessage(
            SynthCommand.NEW,
            [self._name, self.nodeid, self._add_action.value, self._target_id]
            + flatten_args,
        )
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True, await_reply=False)
        return self

    def get(self, control: str) -> Any:
        """Get a Synth argument

        This will request the value from scsynth with /s_get(n).

        Parameters
        ----------
        control : str
            name of the Synth control argument
        """
        with self._state_lock:
            if (
                self._synth_desc is not None
            ):  # change from synth_desc to self._current_controls
                try:
                    default_value = self._synth_desc[control].default
                except KeyError as error:
                    raise ValueError(
                        f"argument '{control}' not in synth_desc"
                        f"{self._synth_desc.keys()}"
                    ) from error
            else:
                default_value = None
        # if we know they type of the argument and its list we use s_getn
        if default_value is not None and isinstance(default_value, list):
            command = SynthCommand.S_GETN
            msg_params = [self.nodeid, control, len(default_value)]
        else:
            command = SynthCommand.S_GET
            msg_params = [self.nodeid, control]

        msg = OSCMessage(command, msg_params)
        try:
            reply = self.server.send(msg, bundle=False)
        except OSCCommunicationError as osc_error:
            if command in self.server.fails:
                fail = self.server.fails.msg_queues[command].get(timeout=0)
                if f"Node {self.nodeid} not found" in fail:
                    raise RuntimeError(
                        f"Node {self.nodeid} cannot be found"
                    ) from osc_error
            raise
        else:
            if default_value is not None and isinstance(default_value, list):
                nodeid, name, _, *values = reply
                ret_val = list(values)
            else:  # default s_get
                nodeid, name, ret_val = reply
            if self.nodeid == nodeid and name == control:
                self.current_controls[control] = ret_val
                return ret_val
            else:
                raise RuntimeError("Received msg with wrong node id")

    def seti(self, *args):
        """Set part of an arrayed control."""
        raise NotImplementedError()

    def __getattr__(self, name):
        # python will try obj.__getattribute__(name) before this
        if self._initialized:
            with self._state_lock:
                if (
                    name in self._current_controls
                    or self._synth_desc
                    and name in self._synth_desc
                ):
                    return self.get(name)
        raise AttributeError(
            f"'{type(self).__name__}' object has no attribute '{name}'"
        )

    def __setattr__(self, name, value):
        # First try regular attribute access.
        # This is done similiar in pandas NDFrame.
        try:
            object.__getattribute__(self, name)
            return object.__setattr__(self, name, value)
        except AttributeError:
            pass

        # First time the _initialized and _server is not set
        # and then it is false until Synth instance is done with __init__
        if name in ["_server", "_initialized"] or not self._initialized:
            return super().__setattr__(name, value)
        # if initialized try setting current controls
        with self._state_lock:
            if name in self._current_controls or (
                self._synth_desc and name in self._synth_desc
            ):
                return self.set(name, value)
        warnings.warn(
            f"Setting '{name}' as python attribute and not as Synth Parameter. "
            "SynthDesc is unknown. sclang must be running and knowing this SynthDef "
            "Use set method when using Synths without SynthDesc to set Synth Parameters."
        )
        super().__setattr__(name, value)

    def __repr__(self) -> str:
        status = self._get_status_repr()
        return (
            f"<Synth({self.nodeid}) '{self._name}' {status} {self._current_controls}>"
        )


class Group(Node):
    """Representation of a Group on SuperCollider."""

    def __init__(
        self,
        *,
        nodeid: Optional[int] = None,
        new: bool = True,
        parallel: bool = False,
        add_action: AddAction = AddAction.TO_HEAD,
        target: Optional[Union[Node, int]] = None,
        server: Optional["SCServer"] = None,
    ) -> None:
        """Create a Python representation of a SuperCollider group.

        Parameters
        ----------
        nodeid : int, optional
            ID of the node in SuperCollider, by default sc3nb will create one.
            Can be set to an existing id to create a Python instance of a running Node.
        new : bool, optional
            True if synth should be created on the server, by default True
            Should be False if creating an instance of a running Node.
        parallel : bool, optional
            If True create a parallel group, by default False
        add_action : AddAction or int, optional
            Where the Group should be added, by default AddAction.TO_HEAD (0)
        target : Node or int, optional
            AddAction target, if None it will be the default group of the server
        server : SCServer, optional
            Server instance where this Group is located,
            by default use the SC default server
        """
        self._server = server or sc3nb.SC.get_default().server
        if nodeid in self._server.nodes:
            if new:
                self.new(add_action=add_action, target=target)
            return

        super().__init__(
            nodeid=nodeid,
            add_action=add_action,
            target=target,
            server=server,
        )
        with self._state_lock:
            self._parallel = parallel
            self._children = []

        if new:
            self.new(add_action=self._add_action, target=self._target_id)

    def _update_group_state(
        self,
        children: Optional[Sequence[Node]] = None,
    ) -> None:
        _LOGGER.debug("Update Group(%s)", self.nodeid)
        with self._state_lock:
            if children is not None:
                self._children = children

    def new(
        self,
        add_action=AddAction.TO_HEAD,
        target=None,
        *,
        parallel=None,
        return_msg=False,
    ) -> Union["Group", OSCMessage]:
        """Creates the synth on the server with g_new / p_new.

        Attention: Here you create an identical group! Same nodeID etc.
        - This will fail if there is already this nodeID on the SuperCollider server!

        Parameters
        ----------
        add_action : AddAction or int, optional
            where the group should be added, by default AddAction.TO_HEAD (0)
        target : Node or int, optional
            add action target, by default 1
        parallel : bool, optional
            If True use p_new, by default False
        return_msg : bool, optional
            If ture return the OSCMessage instead of sending it, by default False

        Returns
        -------
        Group
            self
        """
        with self._state_lock:
            super().new(target=target, add_action=add_action)
            if parallel is not None:
                self._parallel = parallel
            new_command = GroupCommand.P_NEW if self._parallel else GroupCommand.G_NEW
        msg = OSCMessage(
            new_command, [self.nodeid, self._add_action.value, self._target_id]
        )
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True, await_reply=False)
        return self

    @property
    def children(self) -> Sequence[Node]:
        """Return this groups children as currently known

        Returns
        -------
        Sequence[Node]
            Sequence of child Nodes (Synths or Groups)
        """
        return self._children

    def move_node_to_head(self, node, return_msg=False):
        """Move node to this groups head with g_head.

        Parameters
        ----------
        node : Node
            node to move
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        Group
            self
        """
        msg = OSCMessage(GroupCommand.HEAD, [self.nodeid, node.nodeid])
        self.server.send(msg, bundle=True)
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True)
        return self

    def move_node_to_tail(self, node, return_msg=False):
        """Move node to this groups tail with g_tail.

        Parameters
        ----------
        node : Node
            node to move
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        Group
            self
        """
        msg = OSCMessage(GroupCommand.TAIL, [self.nodeid, node.nodeid])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True)
        return self

    def free_all(self, return_msg=False):
        """Frees all nodes in the group with g_freeAll.

        Parameters
        ----------
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        OSCMessage
            if return_msg else self
        """
        self._children = []
        msg = OSCMessage(GroupCommand.FREE_ALL, [self.nodeid])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True)
        return self

    def deep_free(self, return_msg=False):
        """Free all synths in this group and its sub-groups with g_deepFree.

        Sub-groups are not freed.

        Parameters
        ----------
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        OSCMessage
            if return_msg else self
        """
        with self._state_lock:
            self._children = [c for c in self._children if isinstance(c, Group)]
        msg = OSCMessage(GroupCommand.DEEP_FREE, [self.nodeid])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True)
        return self

    def dump_tree(self, post_controls=True, return_msg=False):
        """Posts a representation of this group's node subtree with g_dumpTree.

        Parameters
        ----------
        post_controls : bool, optional
            True for control values, by default False
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        OSCMessage
            if return_msg else self
        """
        msg = OSCMessage(
            GroupCommand.DUMP_TREE, [self.nodeid, 1 if post_controls else 0]
        )
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundle=True)
        return self

    def query_tree(self, include_controls=False) -> "Group":
        """Send a g_queryTree message for this group.

        See https://doc.sccode.org/Reference/Server-Command-Reference.html#/g_queryTree for details.

        Parameters
        ----------
        include_controls : bool, optional
            True for control values, by default False

        Returns
        -------
        tuple
            /g_queryTree.reply
        """
        msg = OSCMessage(
            GroupCommand.QUERY_TREE, [self.nodeid, 1 if include_controls else 0]
        )
        _, *nodes_info = self.server.send(msg)
        NodeTree(
            info=nodes_info,
            root_nodeid=self.nodeid,
            controls_included=include_controls,
            start=0,
            server=self.server,
        )
        return self

    def _repr_pretty_(self, printer, cylce):
        status = self._get_status_repr()
        if cylce:
            printer.text(f"Group({self.nodeid}) {status}>")
        else:
            printer.text(f"Group({self.nodeid}) {status} {self._current_controls}")
            with printer.group(2, " children=[", "]"):
                if self._children:
                    printer.breakable()
                    for idx, child in enumerate(self._children):
                        if idx:
                            printer.text(",")
                            printer.breakable()
                        printer.pretty(child)

    def __repr__(self) -> str:
        status = self._get_status_repr()
        return f"<Group({self.nodeid}) {status} {self._current_controls} children={self.children}>"


class NodeTree:
    """Node Tree is a class for parsing /g_queryTree.reply"""

    def __init__(
        self,
        info: Sequence[Any],
        root_nodeid: int,
        controls_included: bool,
        start: int = 0,
        server: Optional["SCServer"] = None,
    ) -> None:
        self.controls_included = controls_included
        self.root_nodeid = root_nodeid
        parsed, self.root = NodeTree.parse_nodes(info, controls_included, start, server)
        assert len(info) == parsed, "Mismatch in nodes info length and parsed info"

    @staticmethod
    def parse_nodes(
        info: Sequence[Any],
        controls_included: bool = True,
        start: int = 0,
        server: Optional["SCServer"] = None,
    ) -> Tuple[int, Node]:
        """Parse Nodes from reply of the /g_queryTree cmd of scsynth.
        This reads the /g_queryTree.reply and creates the corresponding Nodes in Python.
        See https://doc.sccode.org/Reference/Server-Command-Reference.html#/g_queryTree

        Parameters
        ----------
        controls_included : bool
            If True the current control (arg) values for synths will be included
        start : int
            starting position of the parsing, used for recursion, default 0
        info : Sequence[Any]
            /g_queryTree.reply to be parsed.

        Returns
        -------
        Tuple[int, Node]
            postion where the parsing ended, resulting Node
        """
        pos = start + 2
        nodeid, num_children = info[start:pos]
        if num_children < 0:  # -1 children ==> synth
            symbol = info[pos:][0]
            pos += 1
            num_controls = None
            controls = None
            if controls_included:
                num_controls = info[pos:][0]
                pos += 1
                controls_size = 2 * num_controls
                controls_info = info[pos:][:controls_size]
                controls = dict(zip(controls_info[::2], controls_info[1::2]))
                pos += controls_size
            return (
                pos,
                Synth(
                    name=symbol,
                    controls=controls,
                    nodeid=nodeid,
                    new=False,
                    server=server,
                ),
            )
        # num_children >= 0 ==> group
        children = []
        to_parse = num_children
        while to_parse > 0:
            # is group
            pos, node = NodeTree.parse_nodes(info, controls_included, pos, server)
            node._group = nodeid
            children.append(node)
            to_parse -= 1
        group = Group(nodeid=nodeid, new=False, server=server)
        group._update_group_state(children=children)
        return pos, group

    def _repr_pretty_(self, printer, cylce):
        if cylce:
            printer.text(f"NodeTree root={self.root_nodeid}")
        else:
            printer.text("NodeTree root=")
            printer.pretty(self.root)
