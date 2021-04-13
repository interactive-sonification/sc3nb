"""Implements Node and subclasses Synth and Group."""

import logging
import warnings
from abc import ABC, abstractmethod
from enum import Enum, unique
from functools import reduce
from operator import iconcat
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    NamedTuple,
    Optional,
    Sequence,
    Tuple,
    Union,
)

from pythonosc.osc_message import OscMessage

import sc3nb
from sc3nb.osc.osc_communication import OSCCommunicationError, build_message
from sc3nb.sc_objects.synthdef import SynthDef

if TYPE_CHECKING:
    from sc3nb.sc_objects.server import SCServer
    from sc3nb.sclang import SynthArgument

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())


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


class State(Enum):
    """State for playing and running"""

    PROBABLY_TRUE = True
    PROBABLY_FALSE = False
    TRUE = True
    FALSE = False
    UNKNOWN = 0


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
        *args,
        nodeid: Optional[int] = None,
        server: Optional["SCServer"] = None,
        **kwargs: Dict,
    ) -> "Node":
        if nodeid is not None:
            if server is None:
                server = sc3nb.SC.get_default().server
            try:
                node = server.nodes[nodeid]
                if node:
                    # check here if nodes are compatible
                    if isinstance(node, cls):
                        _LOGGER.debug(
                            "Return Node (%s) %s from %s", nodeid, node, server
                        )
                        return node
                    else:
                        raise RuntimeError(
                            f"Tried to get {node} from {server}"
                            f" as {cls} but type is {type(node)}"
                        )
            except KeyError:
                pass
        _LOGGER.debug("Node (%s) not in Server: %s", nodeid, server)
        return super().__new__(cls)

    @abstractmethod
    def __init__(
        self,
        *,
        nodeid: Optional[int] = None,
        group: Optional[Union["Group", int]] = None,
        add_action: Optional[Union[AddAction, int]] = None,
        target: Optional[Union["Node", int]] = None,
        server: Optional["SCServer"] = None,
    ) -> None:
        """Create a new Node

        Parameters
        ----------
        nodeid : int or None
            This Nodes node id or None
        group : Node or int or None
            This Nodes nodeid or the corresponding Node, by default None means it will be derived
        add_action : AddAction or corresponding int, optional
            This Nodes AddAction when created in Server, by default None
        target : Node or int or None, optional
            This Nodes AddActions target, by default None
        server : SCServer, optional
            The Server for this node, by default server
        """
        self._server = server or sc3nb.SC.get_default().server
        if nodeid in self._server.nodes:
            raise RuntimeError("The __init__ of Node should not be called twice")

        self._nodeid = nodeid if nodeid is not None else self._server.allocate_node_id()
        if group is not None:
            self._group = Node._get_nodeid(group)
        if target is not None:
            self._target_id = Node._get_nodeid(target)
        else:
            self._target_id = None
        self._set_node_attrs(target, add_action)

        _LOGGER.debug("Adding Node (%s) to %s", self._nodeid, self._server)
        self._server.nodes[self._nodeid] = self

        # only with node watcher
        self._is_playing = State.UNKNOWN
        self._is_running = State.UNKNOWN

        # this is state that we cannot really be sure of
        self._current_args = {}

    def _set_node_attrs(
        self,
        target: Optional[Union["Node", int]],
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
        # get target id
        if target is not None:
            self._target_id = Node._get_nodeid(target)
        else:
            if self._target_id is None:
                self._target_id = self.server.default_group.nodeid

        # get add action
        if add_action is None:
            self._add_action = AddAction.TO_HEAD
        elif isinstance(add_action, int):
            self._add_action = AddAction(add_action)
        else:
            self._add_action = add_action

        # derive group
        if self._add_action in [AddAction.TO_HEAD, AddAction.TO_TAIL]:
            self._group = self._target_id
        elif self._group is None:  # AddAction BEFORE, AFTER or REPLACE
            if isinstance(target, Node):
                self._group = target.group
            elif target in self._server.nodes:
                target_node = self._server.nodes[target]
                if target_node:
                    self._group = target_node.group
            else:
                _LOGGER.warning("Could not derive group of Node, assuming group 0")
                self._group = 0
        _LOGGER.debug(
            "Node attrs after setting: nodeid %s, group %s, addaction %s, target %s",
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
    def group(self) -> int:
        """Identifier of this nodes group."""
        return self._group

    @property
    def server(self):
        """The server on which this node is located."""
        return self._server

    @property
    def is_playing(self):
        """True if this node is playing."""
        return self._is_playing

    @property
    def is_running(self):
        """True if this node is running."""
        return self._is_running

    def free(self, return_msg=False):
        """Free the node with /n_free.

        This will set is_running and is_playing to false.
        Even when the message is returned to mimic the behavior of the SuperCollider Node
        See https://doc.sccode.org/Classes/Node.html#-freeMsg"""
        self._is_running = State.PROBABLY_FALSE
        self._is_playing = State.PROBABLY_FALSE
        msg = build_message(NodeCommand.FREE, [self.nodeid])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def run(self, flag=True, return_msg=False):
        """Turn node on or off with n_run"""
        msg = build_message(NodeCommand.RUN, [self.nodeid, 0 if flag is False else 1])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
            self._is_running = State.PROBABLY_TRUE if flag else State.PROBABLY_FALSE
        return self

    def set(self, argument, *values, return_msg=False):
        """Set a control value(s) of the node with n_set.

        Parameters
        ----------
        argument : string | dict | list
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
        if isinstance(argument, dict):
            msg_args = []
            for arg, val in argument.items():
                msg_args.append(arg)
                msg_args.append(val)
                self._update_arg(arg, val)
        elif isinstance(argument, list):
            for arg_idx, arg in enumerate(argument):
                if isinstance(arg, str):
                    self._update_arg(arg, argument[arg_idx + 1])
            msg_args = argument
        else:
            if len(values) == 1:
                self._update_arg(argument, values[0])
            else:
                self._update_arg(argument, values)
            msg_args = [argument] + list(values)
        msg = build_message(NodeCommand.SET, [self.nodeid] + msg_args)
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def _update_arg(self, argument, value):
        try:
            val = object.__getattribute__(self, argument)
        except AttributeError:
            pass
        else:
            warnings.warn(
                f"attribute {argument}={val} is deleted and recognized as Node Parameter now"
            )
            delattr(self, argument)
        if not argument.startswith("t_"):
            self._current_args[argument] = value

    def _update_args(self, args: Optional[dict] = None):
        if args is not None:
            for arg, val in args.items():
                self._update_arg(arg, val)

    def fill(self, control, num_controls, value, return_msg=False):
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
        OscMessage
            if return_msg else self
        """
        msg = build_message(
            NodeCommand.FILL, [self.nodeid, control, num_controls, value]
        )
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def map(self, control, bus, return_msg=False):
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
        OscMessage
            if return_msg else self
        """
        msg_args = [self.nodeid, control, bus.idxs[0]]
        if bus.num_channels > 1:
            map_command = NodeCommand.MAPAN if bus.is_audio_bus() else NodeCommand.MAPN
            msg_args.append(bus.num_channels)
        else:
            map_command = NodeCommand.MAPA if bus.is_audio_bus() else NodeCommand.MAP
        msg = build_message(map_command, msg_args)
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def release(self, release_time=None, return_msg=False):
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
        OscMessage
            if return_msg else self
        """
        if release_time is not None:
            if release_time <= 0:
                release_time = 1
            else:
                release_time = -1 * (release_time + 1)
        else:
            release_time = 0

        msg = build_message(NodeCommand.SET, [self.nodeid, "gate", release_time])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
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
        msg = build_message(NodeCommand.QUERY, [self.nodeid])
        nodeid, group, prev_nodeid, next_nodeid, *rest = self.server.send(msg)
        if len(rest) == 1 and rest[0] == 0:  # node is synth
            return SynthInfo._make([nodeid, group, prev_nodeid, next_nodeid])
        else:
            _, head, tail = rest
            return GroupInfo._make(
                [nodeid, group, prev_nodeid, next_nodeid, head, tail]
            )

    def trace(self, return_msg=False):
        """Trace a node.

        Print out values of the inputs and outputs for one control period.
        If node is a group then print the node IDs and names of each node.

        Parameters
        ----------
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        OscMessage
            if return_msg else self
        """
        msg = build_message(NodeCommand.TRACE, [self.nodeid])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def move(
        self, add_action: AddAction, another_node: "Node", return_msg: bool = False
    ) -> Optional[OscMessage]:
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
        OscMessage or None
            if return_msg this will be the OscMessage

        Raises
        ------
        ValueError
            If a wrong AddAction was provided
        """
        if add_action == AddAction.REPLACE:
            raise ValueError(
                "add_action needs to be in [TO_HEAD, TO_TAIL, AFTER, BEFORE]"
            )
        msg = build_message(
            NodeCommand.ORDER, [add_action.value, another_node.nodeid, self.nodeid]
        )
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    # NodeWatcher needed

    def register(self):
        """Register to be watched."""
        raise NotImplementedError()

    def unregister(self):
        """Unregister to stop being watched."""
        raise NotImplementedError()

    def on_free(self, func):
        """Callback that is executed when this Synth is freed"""
        raise NotImplementedError()

    def wait(self, func):
        """Wait until this Node is freed"""
        raise NotImplementedError()

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
        args: Dict[str, Any] = None,
        *,
        nodeid: Optional[int] = None,
        new: bool = True,
        add_action: Optional[Union[AddAction, int]] = None,
        target: Optional[Union["Node", int]] = None,
        group: Optional[Union["Group", int]] = None,
        server: Optional["SCServer"] = None,
    ):
        """Create a Python representation of a SuperCollider synth.

        Parameters
        ----------
        sc : SC
            sc3nb SuperCollider instance
        name : str, optional
            name of the synth to be created, by default "default"
        args : dict, optional
            synth arguments, by default None
        nodeid : int, optional
            ID of the node in SuperCollider, by default sc will create one
        new : bool, optional
            True if synth should be created on the server, by default True
        add_action : AddAction or int, optional
            where the synth should be added, by default AddAction.TO_HEAD (0)
        target : Node or int, optional
            add action target, by default 1

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
            _LOGGER.debug("Update Synth (%s)", nodeid)
            self._update_state(name=name, args=args)
            if new:
                self.new(args=args, add_action=add_action, target=target)
            return

        # attention: this must be the first line. see __setattr__, __getattr__
        self._initialized = False
        super().__init__(
            nodeid=nodeid,
            group=group,
            add_action=add_action,
            target=target,
            server=server,
        )

        if name is None:
            name = "default"
        self._name = name
        if args is None:
            args = {}
        self._current_args = args

        self._synth_desc = SynthDef.get_description(name)

        # attention: this must be after every attribute is set
        self._initialized = True
        if new:
            self.new(
                args=self._current_args,
                add_action=self._add_action,
                target=self._target_id,
            )

    def _update_state(self, name: Optional[str], args: Optional[dict]):
        if name is not None:
            self._name = name
            self._synth_desc = SynthDef.get_description(name)
        self._update_args(args)

    @property
    def synth_desc(self) -> Optional[Dict[str, "SynthArgument"]]:
        """This Synths SynthDef name."""
        if self._synth_desc is None:
            self._synth_desc = SynthDef.get_description(self._name)
        return self._synth_desc

    @property
    def name(self) -> str:
        """This Synths SynthDef name."""
        return self._name

    @property
    def current_args(self) -> Dict[str, Any]:
        """This Synth currently cached args."""
        return self._current_args

    def new(
        self,
        args: Optional[dict] = None,
        add_action: Optional[Union[AddAction, int]] = None,
        target: Optional[Union[Node, int]] = None,
        return_msg: bool = False,
    ) -> Union["Synth", OscMessage]:
        """Creates the synth on the server with s_new.

        Attention: Here you create an identical synth! Same nodeID etc.
        - This will fail if there is already this nodeID on the SuperCollider server!
        """
        self._set_node_attrs(target=target, add_action=add_action)

        self._is_playing = State.PROBABLY_TRUE
        self._is_running = State.PROBABLY_TRUE

        self._update_args(args)
        flatten_args = reduce(iconcat, self._current_args.items(), [])
        msg = build_message(
            SynthCommand.NEW,
            [self._name, self.nodeid, self._add_action.value, self._target_id]
            + flatten_args,
        )
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True, await_reply=False)
        return self

    def get(self, argument: str) -> Any:
        """Get a synth argument

        This will request the value from scsynth with s_get(n).

        Parameters
        ----------
        argument : str
            name of the synth argument
        """
        if self._synth_desc is not None:  # change from synth_desc to self._current_args
            try:
                default_value = self._synth_desc[argument].default
            except KeyError as error:
                raise ValueError(
                    f"argument '{argument}' not in synth_desc"
                    f"{self._synth_desc.keys()}"
                ) from error
        else:
            default_value = None
        # if we know they type of the argument and its list we use s_getn
        if default_value is not None and isinstance(default_value, list):
            command = SynthCommand.S_GETN
            args = [self.nodeid, argument, len(default_value)]
        else:
            command = SynthCommand.S_GET
            args = [self.nodeid, argument]

        msg = build_message(command, args)
        try:
            reply = self.server.send(msg)
        except OSCCommunicationError as osc_error:
            if command in self.server.fails:
                fail = self.server.fails.msg_queues[command].get(timeout=0)
                print(f"FAIL - {fail} - {f'Node {self.nodeid} not found' in fail}")
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
            if self.nodeid == nodeid and name == argument:
                self.current_args[argument] = ret_val
                return ret_val
            else:
                raise RuntimeError("Received msg with wrong node id")

    def seti(self, args):
        """Set part of an arrayed control."""
        raise NotImplementedError()

    def __getattr__(self, name):
        # python will try obj.__getattribute__(name) before this
        if self._initialized:
            if (
                name in self._current_args
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
        elif self._initialized:
            if (
                name in self._current_args
                or self._synth_desc
                and name in self._synth_desc
            ):
                return self.set(name, value)
        warnings.warn(
            f"Setting '{name}' as python attribute and not as Synth Parameter. "
            "SynthDesc is unknown. sclang must be running and knowing this SynthDef "
            "Use set method when using Synths without SynthDesc to set Synth Parameters."
        )
        super().__setattr__(name, value)

    def _repr_pretty_(self, p, cylce):
        if cylce:
            p.text(f"Synth ({self.nodeid}) '{self._name}'")
        else:
            p.text(f"Synth ({self.nodeid}) '{self._name}' {self._current_args}")


class Group(Node):
    """Representation of a Group on SuperCollider."""

    def __init__(
        self,
        nodeid: Optional[int] = None,
        *,
        new: bool = True,
        parallel: bool = False,
        add_action: AddAction = AddAction.TO_HEAD,
        target: Optional[Union[Node, int]] = None,
        group: Optional[Union["Group", int]] = None,
        children: Optional[Sequence[Node]] = None,
        server: Optional["SCServer"] = None,
    ) -> None:
        """Create a Python representation of a SuperCollider group.

        Parameters
        ----------
        sc : SC
            sc3nb SuperCollider instance
        nodeid : int, optional
            ID of the node in SuperCollider, by default sc will create one
        new : bool, optional
            True if synth should be created on the server, by default True
        parallel : bool, optional
            If True create a parallel group, by default False
        add_action : AddAction or int, optional
            where the synth should be added, by default AddAction.TO_HEAD (0)
        target : Node or int, optional
            add action target, by default 1
        """
        self._server = server or sc3nb.SC.get_default().server
        if nodeid in self._server.nodes:
            _LOGGER.debug("Update Group (%s)", nodeid)
            self._update_state(group, children)
            return

        super().__init__(
            nodeid=nodeid,
            group=group,
            add_action=add_action,
            target=target,
            server=server,
        )

        self._parallel = parallel
        if children is None:
            children = []
        self._children = children

        if new:
            self.new(add_action=self._add_action, target=self._target_id)

    def _update_state(
        self,
        group: Optional[Union[Node, int]] = None,
        children: Optional[Sequence[Node]] = None,
    ) -> None:
        if group:
            self._group = Node._get_nodeid(group)
        if children is not None:
            self._children = children

    def new(
        self, parallel=None, add_action=AddAction.TO_HEAD, target=None, return_msg=False
    ):
        """Creates the synth on the server with g_new / p_new.

        Attention: Here you create an identical group! Same nodeID etc.
        - This will fail if there is already this nodeID on the SuperCollider server!

        Parameters
        ----------
        parallel : bool, optional
            If True use p_new, by default None
        add_action : AddAction or int, optional
            where the group should be added, by default AddAction.TO_HEAD (0)
        target : Node or int, optional
            add action target, by default 1
        return_msg : bool, optional
            If ture return the OscMessage instead of sending it, by default False

        Returns
        -------
        Group
            self
        """
        if parallel is not None:
            self._parallel = parallel
        self._set_node_attrs(target=target, add_action=add_action)

        self._is_playing = State.PROBABLY_TRUE
        self._is_running = State.UNKNOWN

        if self._parallel:
            new_command = GroupCommand.P_NEW
        else:
            new_command = GroupCommand.G_NEW
        msg = build_message(
            new_command, [self.nodeid, self._add_action.value, self._target_id]
        )
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
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

    def move_node_to_head(self, node):
        """Move node to this groups head with g_head.

        Parameters
        ----------
        node : Node
            node to move

        Returns
        -------
        Group
            self
        """
        msg = build_message(GroupCommand.HEAD, [self.nodeid, node.nodeid])
        self.server.send(msg, bundled=True)
        return self

    def move_node_to_tail(self, node):
        """Move node to this groups tail with g_tail.

        Parameters
        ----------
        node : Node
            node to move

        Returns
        -------
        Group
            self
        """
        msg = build_message(GroupCommand.TAIL, [self.nodeid, node.nodeid])
        self.server.send(msg, bundled=True)
        return self

    def free_all(self, return_msg=False):
        """Frees all nodes in the group with g_freeAll.

        Parameters
        ----------
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        OscMessage
            if return_msg else self
        """
        self._children = []
        msg = build_message(GroupCommand.FREE_ALL, [self.nodeid])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
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
        OscMessage
            if return_msg else self
        """
        self._children = [c for c in self._children if isinstance(c, Group)]
        msg = build_message(GroupCommand.DEEP_FREE, [self.nodeid])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
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
        OscMessage
            if return_msg else self
        """
        msg = build_message(
            GroupCommand.DUMP_TREE, [self.nodeid, 1 if post_controls else 0]
        )
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def query_tree(self, include_controls=False):
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
        msg = build_message(
            GroupCommand.QUERY_TREE, [self.nodeid, 1 if include_controls else 0]
        )
        _, *nodes_info = self.server.send(msg)
        return NodeTree(
            info=nodes_info,
            root_nodeid=self.nodeid,
            controls_included=include_controls,
            start=0,
            server=self.server,
        )

    def _repr_pretty_(self, p, cylce):
        if cylce:
            p.text(f"Group ({self.nodeid})")
        else:
            p.text(f"Group ({self.nodeid}) {self._current_args}")
            with p.group(2, " children=[", "]"):
                if self._children:
                    p.breakable()
                    for idx, child in enumerate(self._children):
                        if idx:
                            p.text(",")
                            p.breakable()
                        p.pretty(child)


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
                    name=symbol, args=controls, nodeid=nodeid, new=False, server=server
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
        return pos, Group(nodeid=nodeid, children=children, new=False, server=server)

    def _repr_pretty_(self, p, cylce):
        if cylce:
            p.text(f"NodeTree root={self.root_nodeid}")
        else:
            p.text("NodeTree root=")
            p.pretty(self.root)
