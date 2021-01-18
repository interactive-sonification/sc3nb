"""Implements Node and subclasses Synth and Group."""

import logging
import warnings
from abc import ABC
from enum import Enum, unique

from functools import reduce
from operator import iconcat

import sc3nb
from sc3nb.osc.osc_communication import build_message
from sc3nb.sc_objects.synthdef import SynthDef

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())

@unique
class AddAction(Enum):
    """Add action codes of SuperCollider"""
    TO_HEAD = 0  # (the default) add at the head of the group specified by target
    TO_TAIL = 1  # add at the tail of the group specified by target
    AFTER = 2    # add immediately after target in its server's node order
    BEFORE = 3   # add immediately before target in its server's node order
    REPLACE = 4  # replace target and take its place in its server's node order
    # Note: A Synth is not a valid target for \addToHead and \addToTail.

class State(Enum):
    """State for playing and running"""
    PROBABLY_TRUE = True
    PROBABLY_FALSE = False
    TRUE = True
    FALSE = False
    UNKNOWN = 0

class Node(ABC):
    """Python representation of a node on the SuperCollider server."""

    def __init__(self, nodeid, server=None):
        self._server = server or sc3nb.SC.default.server

        self._nodeid = nodeid if nodeid is not None else self._server.next_node_id()
        self._add_action = None
        self._target = None
        self._group = None

        # only with node watcher
        self._is_playing = State.UNKNOWN
        self._is_running = State.UNKNOWN

        # this is state that we cannot really be sure of
        self.current_args = {}

    @property
    def nodeid(self):
        """Identifier of node."""
        return self._nodeid

    @property
    def group(self):
        """Identifier of this nodes group."""
        return self._group

    @property
    def server(self):
        return self._server

    @property
    def is_playing(self):
        return self._is_playing

    @property
    def is_running(self):
        return self._is_running

    def free(self, return_msg=False):
        """Free the node with /n_free.

        This will set is_running and is_playing to false.
        Even when the message is returned to mimic the behavior of the SuperCollider Node
        See https://doc.sccode.org/Classes/Node.html#-freeMsg"""
        self._is_running = State.PROBABLY_FALSE
        self._is_playing = State.PROBABLY_FALSE
        msg = build_message("/n_free", [self.nodeid])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def run(self, flag=True, return_msg=False):
        """Turn node on or off with n_run"""
        msg = build_message("/n_run", [self.nodeid, 0 if flag is False else 1])
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
        -------
        synth.set("freq", 400)
        synth.set({"dur": 1, "freq": 400})
        synth.set(["dur", 1, "freq", 400])
        """
        if isinstance(argument, dict):
            msg_args = []
            for arg, val in argument.items():
                msg_args.append(arg)
                msg_args.append(val)
                self._update_args(arg, val)
        elif isinstance(argument, list):
            for arg_idx, arg in enumerate(argument):
                if isinstance(arg, str):
                    self._update_args(arg, argument[arg_idx+1])
            msg_args = argument
        else:
            if len(values) == 1:
                self._update_args(argument, values[0])
            else:
                self._update_args(argument, values)
            msg_args = [argument] + list(values)
        msg = build_message("/n_set", [self.nodeid] + msg_args)
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def _update_args(self, argument, value):
        try:
            val = object.__getattribute__(self, argument)
        except AttributeError:
            pass
        else:
            warnings.warn(f"python attribute {argument}={val} will be deleted and recognized as Node Parameter from now on")
            delattr(self, argument)
        if not argument.startswith("t_"):
            self.current_args[argument] = value

    # def setn(self, control, num_controls, values, return_msg=False):
    #     """Set ranges of control values with n_setn.

    #     Parameters
    #     ----------
    #     control : int or string
    #         control index or name
    #     num_controls : int
    #         number of control values to fill
    #     values : list of float or int
    #         values to set
    #     return_msg : bool, optional
    #         If True return msg else send it directly, by default False

    #     Returns
    #     -------
    #     OscMessage
    #         if return_msg else self
    #     """
    #     msg = build_message("/n_setn", [self.nodeid, control, num_controls, *values])
    #     if return_msg:
    #         return msg
    #     else:
    #         self.server.send(msg)
    #     return self

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
        msg = build_message("/n_fill", [self.nodeid, control, num_controls, value])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def map(self, control, bus_index, audio_bus=False, return_msg=False):
        """Map a node's control to read from a bus using /n_map or /n_mapa.

        Parameters
        ----------
        control : int or string
            control index or name
        bus_index : int
            control/audio bus index
        audio_bus : bool, optional
            True if bus is audio, by default False
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        OscMessage
            if return_msg else self
        """
        map_command = "/n_mapa" if audio_bus else "/n_map"
        msg = build_message(map_command, [self.nodeid, control, bus_index])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def mapn(self, control, bus_index, num_controls, audio_bus=False, return_msg=False):
        """Map a node's control to read from a bus using /n_map or /n_mapa.

        Parameters
        ----------
        control : int or string
            control index or name
        bus_index : int
            control/audio bus index
        num_controls : int
            number of controls to map
        audio_bus : bool, optional
            True if bus is audio, by default False
        return_msg : bool, optional
            If True return msg else send it directly, by default False

        Returns
        -------
        OscMessage
            if return_msg else self
        """
        map_command = "/n_mapan" if audio_bus else "/n_mapn"
        msg = build_message(map_command, [self.nodeid, control, bus_index, num_controls])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def release(self, release_time, return_msg=False):
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
                release_time = -1 * (release_time+1)
        else:
            release_time = 0

        msg = build_message("/n_set", [self.nodeid, "gate", release_time])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def query(self):
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
        tuple
            n_info answer. See above for content description
        """
        msg = build_message("/n_query", [self.nodeid])
        return self.server.send(msg)

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
        msg = build_message("/n_trace", [self.nodeid])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def move(self, add_action, another_node, return_msg=False):
        if add_action == AddAction.REPLACE:
            raise ValueError("add_action needs to be in [TO_HEAD, TO_TAIL, AFTER, BEFORE]")
        msg = build_message("/n_order", [add_action.value, another_node.nodeid, self.nodeid])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    # NodeWatcher needed

    def register(self):
        pass

    def unregister(self):
        pass

    def on_free(self, func):
        pass

    def wait(self, func):
        pass

    def __eq__(self, other):
        return self.nodeid == other.nodeid

    def _repr_pretty_(self, p, cylce):
        name = type(self).__name__
        playing = self.is_playing if self.is_playing is not None else "unknown"
        running = self.is_running if self.is_running is not None else "unknown"
        status = f"playing={playing} running={running}"
        if cylce:
            p.text(f"{name} ({self.nodeid})")
        else:
            p.text(f"{name} ({self.nodeid}) {self.current_args} {status}")

    def __del__(self):
        _LOGGER.debug(
            "freeing deleted node %s with running state %s", self.nodeid, self.is_running)
        self.free()

    def _get_add_action(self, value):
        """Get the wanted add action regarding state and input

        Parameters
        ----------
        value : scn.node.AddAction or int or None
            new value for add action

        Returns
        -------
        scn.node.AddAction
            resulting AddAction
        """
        if value is None:
            return self._add_action
        elif isinstance(value, AddAction):
            return value
        else:
            return AddAction(value)

    def _get_target(self, value=None):
        """Get the wanted target regarding state and input

        Parameters
        ----------
        value : scn.node.Node or int or None
            new value for target

        Returns
        -------
        int
            resulting nodeID
        """
        if value is None:
            return self._target
        elif isinstance(value, Node):
            target = value.nodeid
        else:
            target = value
        self._group = self._target = target
        return target

class Synth(Node):
    """Python representation of a group node on the SuperCollider server."""

    def __init__(self, name="default", args=None, nodeid=None, new=True,
                 add_action=AddAction.TO_HEAD, target=1, server=None):
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

        Example:
        --------
        scn.Synth(sc, "s1", {"dur": 1, "freq": 400})
        """
        # attention: this must be the first line. see __setattr__, __getattr__
        self._initialized = False

        super().__init__(nodeid, server=server)
        try:
            self.synth_desc = SynthDef.get_desc(name)
        except RuntimeWarning:
            warnings.warn("SynthDesc is unknown. SC.default.lang must be running for SynthDescs")
            self.synth_desc = None

        self.name = name

        self._add_action = self._get_add_action(add_action)
        self._target = self._get_target(target)

        if args is None:
            self.current_args = {}
        else:
            self.current_args = args
        if new:
            self.new(self.current_args)
        # attention: this must be the last line
        self._initialized = True

    def new(self, args=None, add_action=None, target=None, return_msg=False):
        """Creates the synth on the server with s_new.

        Attention: Here you create an identical synth! Same nodeID etc.
        - This will fail if there is already this nodeID on the SuperCollider server!
        """
        self._add_action = self._get_add_action(add_action)
        self._target = self._get_target(target)

        self._is_playing = State.PROBABLY_TRUE
        self._is_running = State.PROBABLY_TRUE

        if args is not None:
            self.current_args = args
        flatten_args = reduce(iconcat, self.current_args.items(), [])
        msg = build_message("/s_new",
                            [self.name, self.nodeid, self._add_action.value,
                             self._target] + flatten_args)
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def get(self, argument):
        """Get a synth argument

        This will request the value from scsynth with s_get(n).

        Parameters
        ----------
        argument : string
            name of the synth argument
        """
        if self.synth_desc is not None:
            try:
                default_value = self.synth_desc[argument].default
            except KeyError as error:
                raise ValueError(f"argument '{argument}' not in synth_desc {self.synth_desc.keys()}") from error
        else:
            default_value = None
        # if we know they type of the argument and its list we use s_getn
        if default_value is not None and isinstance(default_value, list):
            msg = build_message("/s_getn", [self.nodeid, argument, len(default_value)])
            nodeid, name, _, *values = self.server.send(msg)
            ret_val = list(values)
        else: # default s_get
            msg = build_message("/s_get", [self.nodeid, argument])
            nodeid, name, ret_val = self.server.send(msg)
        if self.nodeid == nodeid and name == argument:
            return ret_val
        else:
            raise RuntimeError("Received msg with wrong node id")

    def getn(self, index, count, action, return_msg=False):
        raise NotImplementedError()

    def seti(self, args):
        raise NotImplementedError()

    def __getattr__(self, name):
        if self._initialized:
            if name in self.current_args or self.synth_desc and name in self.synth_desc:
                return self.get(name)
        raise AttributeError(f"'{type(self).__name__}' object has no attribute '{name}'")

    def __setattr__(self, name, value):
        # First try regular attribute access.
        # This is done similiar in pandas NDFrame.
        try:
            object.__getattribute__(self, name)
            return object.__setattr__(self, name, value)
        except AttributeError:
            pass

        # First time the _initialized is not set
        # and then it is false until Synth instance is done with __init__
        if name == "_initialized" or not self._initialized:
            return super().__setattr__(name, value)
        elif self._initialized:
            if name in self.current_args or self.synth_desc and name in self.synth_desc:
                return self.set(name, value)
        warnings.warn(
                f"Setting '{name}' as python attribute and not as Synth Parameter. "
                "SynthDesc is unknown. SC.default.lang must be running for SynthDescs. "
                "Use set method when using Synths without SynthDesc to set Synth Parameters.")
        super().__setattr__(name, value)

class Group(Node):
    """Python representation of a group node on the SuperCollider server."""


    def __init__(self, nodeid=None, new=True, parallel=False,
                 add_action=AddAction.TO_HEAD, target=1, server=None):
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
        super().__init__(nodeid=nodeid, server=server)
        self._add_action = self._get_add_action(add_action)
        self._target = self._get_target(target)
        self._parallel = parallel
        if new:
            self.new()


    def new(self, parallel=None, add_action=AddAction.TO_HEAD, target=None, return_msg=False):
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
            [description], by default False

        Returns
        -------
        Group
            self
        """
        if parallel is not None:
            self._parallel = parallel
        self._add_action = self._get_add_action(add_action)
        self._target = self._get_target(target)

        self._is_playing = State.PROBABLY_TRUE
        self._is_running = State.UNKNOWN

        if self._parallel:
            new_command = "p_new"
        else:
            new_command = "g_new"
        msg = build_message(new_command, [self.nodeid, self._add_action.value, self._target])

        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self


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
        msg = build_message("/g_head", [self.nodeid, node.nodeid])
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
        msg = build_message("/g_tail", [self.nodeid, node.nodeid])
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
        msg = build_message("/g_freeAll", [self.nodeid])
        if return_msg:
            return msg
        else:
            self.server.send(msg, bundled=True)
        return self

    def deep_free(self, return_msg=False):
        """Free all synths in this group and all its sub-groups with g_deepFree.

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
        msg = build_message("/g_deepFree", [self.nodeid])
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
        msg = build_message("/g_dumpTree", [self.nodeid, 1 if post_controls else 0])
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
        msg = build_message("/g_queryTree", [self.nodeid, 1 if include_controls else 0])
        return self.server.send(msg, bundled=True)
        