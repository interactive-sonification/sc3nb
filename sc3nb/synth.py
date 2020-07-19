import re
import time

from queue import Empty

from .tools import parse_pyvars


class Synth:

    def __init__(self, sc, name="default", nodeid=None, action=1, target=1,
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
        try:
            self.synth_args = sc.cmdg(
                f"SynthDescLib.global['{name}'].controlNames;")
            self.default_args = {}
            n = 0
            for arg in self.synth_args:
                default = sc.cmdg(
                  f"SynthDescLib.global['{name}'].controls[{n}].defaultValue;")
                if isinstance(default, list):
                    n = n + len(default)
                else:
                    n = n + 1
                self.default_args[arg] = default
        except TimeoutError:
            raise ValueError(
                f"Can't receive synth arguments, is {name} defined?")
        self.name = name
        self.sc = sc
        self.nodeid = nodeid if nodeid is not None else sc.nextNodeID()
        self.action = action
        self.target = target
        if args is None:
            self.current_args = {}
        else:
            self.current_args = args
        self.start()

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
        if args is None:
            args = self.current_args
        flatten_dict = [
            val for sublist in [list((k, v)) for k, v in args.items()]
            for val in sublist]
        self.sc.msg("/s_new",
                    [self.name, self.nodeid, self.action,
                     self.target] + flatten_dict)
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
            pardict = argument
            arglist = [self.nodeid]
            for k, val in argument.items():
                arglist.append(k)
                arglist.append(val)
                if not k.startswith("t_"):
                    self.current_args[k] = val
            self.sc.msg("/n_set", arglist)
        elif isinstance(argument, list):
            self.sc.msg("/n_set", [self.nodeid]+argument)
        else:
            if not argument.startswith("t_"):
                self.current_args[argument] = value
            self.sc.msg("/n_set", [self.nodeid, argument, value]+list(args))
        return self

    def get(self, argument):
        """Get a synth argument

        This will request the value from scsynth with s_get(n).

        Parameters
        ----------
        argument : string
            name of the synth argument
        """
        if isinstance(self.default_args[argument], list):
            return list(
                self.sc.msg("/s_getn", [self.nodeid,
                                        argument,
                                        len(self.default_args[argument])]
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
            (k,v) tuple dict, while k is the searchpattern and v is the
            replacement

        Returns
        -------
        self : object of type SynthDef
            the SynthDef object
        """
        for (k, v) in dictionary.items():
            self.set_context(k, v)
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

    def create(self, pyvars=None, wait=0.1):
        """
        This method will create the current_def as a sc synthDef.
        It will wait until scsynth has hopefully received the synthDef.

        If a synth with the same definition was already in sc, this method
        will only return the name.

        Parameters
        ----------
        pyvars: dict
            SC pyvars dict, to inject python variables
        wait: float, optional
            How long we wait after, default=0.1

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

        # Create new synthDef
        self.sc.cmd(
            f"""SynthDef("{name}", {self.current_def}).add();""",
            pyvars=pyvars)
        # TODO:
        # we wait here as the SynthDef is added
        # asynchronosly to the scsynth server.
        # A better solution would be to use SynthDef.send
        # this could spawn a SendReply synth on scsynth
        time.sleep(wait)
        self.defined_instances[name] = (self.current_def, pyvars)
        return name

    def create_and_reset(self, pyvars={}):
        name = self.create(pyvars)
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


class SynthFamily:

    def __init__(self, sc, name, definition=None, context=None,
                 family_args=None, default_args=None, action=1, target=1,
                 wait=0.1):
        """Create multiple Synth from a SynthDef in a easy way.

        Parameters
        ----------
        sc : SC object
            SC instance where the synthdef should be created
        name : string
            default name of the synthdef creation.
            The naming convention will be name+int, where int is the amount of
            already created synths of this definition
        definition : string
            Pass the default synthdef definition here. Flexible content
            should be in double brackets ("...{{flexibleContent}}...").
            This flexible content, you can dynamic replace with set_context()
        context : list of dicts, optional
            Same as in SynthDef.set_contexts
        family_args : list of dicts, optional
            list of arguments for each synth, by default None
        default_args : dict, optional
            default arguments for all family members, by default None
        action : int, optional
            add action (see s_new), by default 1
        target : int, optional
            add target ID (see s_new), by default 1
        wait : float, optional
            time to wait for SynthDefs, by default 0.1

        Raises
        ------
        ValueError
            When there is context
        """
        if isinstance(context, list):
            if family_args and len(context) != len(family_args):
                raise ValueError(
                    "Lenght of synth context list does not match length of"
                    " the family args")

        if default_args is None:
            default_args = {}

        using_predefined_synth = False
        if definition is None:
            using_predefined_synth = True

        if not using_predefined_synth:
            self.synthDef = sc.SynthDef(
                name=name + "_family_n",
                definition=definition
            )

        synth_info = []
        for n, member_arg in enumerate(family_args):
            if not using_predefined_synth:
                if context:
                    self.synthDef.set_contexts(context[n])
                    synth_name = self.synthDef.create(wait=0.0)
                    self.synthDef.reset()
                else:
                    synth_name = self.synthDef.create(wait=0.0)
            else:
                synth_name = name
            synth_info.append((synth_name, {**default_args, **member_arg}))
        time.sleep(wait)

        self.synths = []
        for synth_name, args in synth_info:
            self.synths.append(sc.Synth(name=synth_name,
                                        args=args,
                                        action=action,
                                        target=target).run(False))

        # TODO: Bug: The Timing is off.
        # This should be send with a bundle all at once.

        self.pause_status = False

    def run(self, flag=True):
        """
        En-/Disable synth running
        """
        for synth in self.synths:
            synth.run(flag)
        self.pause_status = not flag
        return self

    def pause(self, flag=None):
        """
        Pause all synths, or play, if synths are allready paused
        """
        self.run(flag if flag is not None else self.pause_status)
        return self

    def free(self):
        """
        Frees all synths
        """
        for synth in self.synths:
            synth.free()
        return self

    def restart(self):
        """Free and start synths

        Parameters
        ----------
        args : dict, optional
            synth arguments, by default None
        """
        for synth in self.synths:
            synth.restart()
        return self

    def start(self):
        """Starts all synths"""
        for synth in self.synths:
            synth.start()
        return self

    def set(self, argument, value=None, iter_value=False):
        """Set control arguments of the synths.

        Parameters
        ----------
        argument : string
            argument to be set
        value : iterable of any or any, optional
            value of argument, by default None
            If a iterable is provide it must have the lenght of self.synths
            If a non iterable is provided the same value is used for all synths
        iter_value : boolean, optional
            force to use the (iterable) value for all synths, default False

        Raises
        ------
        ValueError
            When a iterable is provided that is not long enough
            and not using iter_value = True
        """
        if hasattr(value, '__iter__') or iter_value:
            if len(value) != len(self.synths):
                raise ValueError("Not enough values provided.")
            for n, v in enumerate(value):
                self.synths[n].set(argument, v)
        else:
            for synth in self.synths:
                synth.set(argument, value)
        return self

    def get(self, argument):
        """Get the current value of the synths

        Parameters
        ----------
        argument : string
            name of the argument
        """
        values = []
        for synth in self.synths:
            values.append(synth.get(argument))
        return values