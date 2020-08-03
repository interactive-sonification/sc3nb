"""Module to for using SuperCollider SynthDefs and Synths in Python"""

import re

from collections import namedtuple
from functools import reduce
from operator import iconcat

from .tools import parse_pyvars


SynthArgument = namedtuple('SynthArgument', ['rate', 'default'])


def get_synth_desc(sc, synth_def):
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
    cmdstr = r"""SynthDescLib.global[{{synthDef}}].controls.collect(
            { arg control;
            [control.name, control.rate, control.defaultValue]
            })""".replace('{{synthDef}}', f"'{synth_def}'")
    synth_desc = sc.cmdg(cmdstr)
    return {s[0]: SynthArgument(*s[1:]) for s in synth_desc if s[0] != '?'}


class Synth:
    """Wrapper for the SuperCollider Synth"""

    def __init__(self, sc, name="default", nodeid=None, start=True, action=1, target=1,
                 args=None):
        """Creates a new Synth with given supercollider instance, name
        and a dict of arguments to the synth.

        Parameters
        ----------
        sc : SC
            sc3nb SuperCollider instance
        name : str, optional
            name of the synth to be created, by default "default"
        nodeid : int, optional
            ID of the node in SuperCollider, by default sc will create one
        action : int, optional
            add action (see s_new), by default 1
        target : int, optional
            add target ID (see s_new), by default 1
        args : dict, optional
            synth arguments, by default None

        Raises
        ------
        ValueError
            Raised when synth can't be found via SynthDescLib.global

        Example:
        --------
        stk.Synth(sc=sc, args={"dur": 1, "freq": 400}, name="s1")
        """
        # attention: synth_args must be set first!
        # synth_args is used in setattr, getattr below!
        self.synth_args = get_synth_desc(sc, name)
        self.name = name
        self.sc = sc
        self.nodeid = nodeid if nodeid is not None else sc.next_node_id()
        self.action = action
        self.target = target
        self.freed = False
        self.pause_status = False
        if args is None:
            self.current_args = {}
        else:
            self.current_args = args
        if start:
            self.start(self.current_args)

    def run(self, flag=True):
        """
        En-/Disable synth running
        """
        self.sc.msg("/n_run", [self.nodeid, 0 if flag is False else 1])
        self.pause_status = not flag
        return self

    def pause(self, flag=None):
        """
        Pause a synth, or play it, if synth is already paused
        """
        self.run(flag if flag is not None else self.pause_status)
        return self

    def free(self):
        """
        Frees a synth with n_free
        """
        self.freed = True
        self.sc.msg("/n_free", [self.nodeid])
        return self

    def restart(self, args=None):
        """Free and start synth

        Parameters
        ----------
        args : dict, optional
            synth arguments, by default None
        """
        if not self.freed:
            self.free()
        self.start(args)

    def start(self, args=None):
        """Starts the synth

        This will send a s_new command to scsynth.
        Attention: Here you create an identical synth! Same synth node etc.
        - use this method only, if your synth is freed before!
        """
        self.freed = False
        self.pause_status = False
        if args is not None:
            self.current_args = args
        flatten_args = reduce(iconcat, self.current_args.items(), [])
        self.sc.msg("/s_new",
                    [self.name, self.nodeid, self.action,
                     self.target] + flatten_args)
        return self

    def set(self, argument, value=None, *args):
        """Set a control argument of the synth

        This will send a n_set command to scsynth.

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
            arglist = [self.nodeid]
            for arg, val in argument.items():
                arglist.append(arg)
                arglist.append(val)
                self._update_args(arg, val)
            self.sc.msg("/n_set", arglist)
        elif isinstance(argument, list):
            for arg_idx, arg in enumerate(argument):
                if isinstance(arg, str):
                    self._update_args(arg, argument[arg_idx+1])
            self.sc.msg("/n_set", [self.nodeid]+argument)
        else:
            self._update_args(argument, value)
            self.sc.msg("/n_set", [self.nodeid, argument, value]+list(args))
        return self

    def _update_args(self, argument, value):
        if not argument.startswith("t_"):
            self.current_args[argument] = value

    def get(self, argument):
        """Get a synth argument

        This will request the value from scsynth with s_get(n).

        Parameters
        ----------
        argument : string
            name of the synth argument
        """
        default_value = self.synth_args[argument].default
        if isinstance(default_value, list):
            return list(
                self.sc.msg("/s_getn", [self.nodeid,
                                        argument,
                                        len(default_value)]
                            )[3:])
        else:
            return self.sc.msg("/s_get", [self.nodeid, argument])[2]

    def __getattr__(self, name):
        if name in self.synth_args:
            return self.get(name)
        raise AttributeError

    def __setattr__(self, name, value):
        if name != 'synth_args' and name in self.synth_args:
            self.set(name, value)
        else:
            super().__setattr__(name, value)

    def __repr__(self):
        status = "paused" if self.pause_status else "running"
        status = status if not self.freed else "freed"
        return f"Synth {self.nodeid} {self.name} {self.current_args} " + \
               f"[{status}]"

    def __del__(self):
        if not self.freed:
            self.free()


class SynthDef:
    """Wrapper for SuperCollider SynthDef"""

    def __init__(self, sc, name, definition):
        """
        Create a dynamic synth definition in sc.

        Parameters
        ----------
        sc: SC object
            SC instance where the synthdef should be created
        name: string
            default name of the synthdef creation.
            The naming convention will be name+int, where int is the amount of
            already created synths of this definition
        definition: string
            Pass the default synthdef definition here. Flexible content
            should be in double brackets ("...{{flexibleContent}}...").
            This flexible content, you can dynamic replace with set_context()
        """
        self.sc = sc
        self.definition = definition
        self.name = name
        self.current_def = definition
        # dict of all already defined synthdefs with this root-defintion
        # (key=name, value=(definition, pyvars))
        self.defined_instances = {}

    def reset(self):
        """
        Reset the current synthdef configuration to the self.definition value.
        After this you can restart your
        configuration with the same root definition

        Returns
        -------
        self : object of type SynthDef
               the SynthDef object
        """
        self.current_def = self.definition
        return self

    def set_context(self, key: str, value):
        """
        This method will replace a given key (format: "...{{key}}...") in the
        synthdef definition with the given value.

        Parameters
        ----------
        key: string
             Searchpattern in the current_def string
        value: string or something with can parsed to string
               Replacement of searchpattern

        Returns
        -------
        self : object of type SynthDef
            the SynthDef object
        """
        self.current_def = self.current_def.replace("{{"+key+"}}", str(value))
        return self

    def set_contexts(self, dictionary: dict):
        """
        Set multiple values at onces when you give a dictionary.
        Because dictionaries are unsorted, keep in mind, that
        the order is sometimes ignored in this method.

        Parameters
        ----------
        dictionary: dict
            {searchpattern: replacement}

        Returns
        -------
        self : object of type SynthDef
            the SynthDef object
        """
        for (searchpattern, replacement) in dictionary.items():
            self.set_context(searchpattern, replacement)
        return self

    def unset_remaining(self):
        """
        This method will remove all existing placeholders in the current def.
        You can use this at the end of definition
        to make sure, that your definition is clean. Hint: This method will
        not remove pyvars

        Returns
        -------
        self : object of type SynthDef
            the SynthDef object

        """
        self.current_def = re.sub(r"{{[^}]+}}", "", self.current_def)
        return self

    def add(self, pyvars=None):
        """
        This method will add the current_def to SuperCollider.

        If a synth with the same definition was already in sc, this method
        will only return the name.

        Parameters
        ----------
        pyvars: dict
            SC pyvars dict, to inject python variables

        Returns
        -------
        string: Name of the synthdef
        """
        # if a synth with the same definition is already defined -> use it
        if (self.current_def, pyvars) in self.defined_instances.values():
            defined_instances = list(self.defined_instances.keys())
            same_idx = defined_instances.index((self.current_def, pyvars))
            return defined_instances[same_idx]

        name = self.name + str(len(self.defined_instances))

        if pyvars is None:
            pyvars = parse_pyvars(self.current_def)

        # Create new SynthDef add it to SynthDescLib and get bytes
        synth_def_blob = self.sc.cmdg(f"""
            r.tmpSynthDef = SynthDef("{name}", {self.current_def});
            SynthDescLib.global.add(r.tmpSynthDef.asSynthDesc);
            r.tmpSynthDef.asBytes();""", pyvars=pyvars)
        self.sc.msg("d_recv", synth_def_blob)
        self.defined_instances[name] = (self.current_def, pyvars)
        return name

    def add_and_reset(self, pyvars=None):
        """Short hand for add and reset

        Parameters
        ----------
        pyvars : dict, optional
            SC pyvars dict, to inject python variables

        Returns
        -------
        string
            name of SynthDef
        """
        name = self.add(pyvars)
        self.reset()
        return name

    def free(self, name: str):
        """

        Parameters
        ----------
        name: str
            Name of the SynthDef, which should be freed. The SynthDef must not
            be created by the current SynthDef object

        Returns
        -------
        self : object of type SynthDef
            the SynthDef object

        """
        self.sc.msg("/d_free", [name])

        # Update defined instances. Important: Don't delete the entry!
        # The naming convention for synthdefs is based on
        # the count of defined_instances, so a deleted key could
        # override an existing synthdef.
        if name in self.defined_instances:
            self.defined_instances[name] = ''
        return self

    def __del__(self):
        """
        Free all SynthDefs, which are defined by this object

        Returns
        -------

        """
        for key in self.defined_instances:
            self.free(key)

    def __repr__(self):
        return f'SynthDef("{self.name}",{self.current_def})'
