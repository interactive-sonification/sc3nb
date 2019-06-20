import re

class Synth:
    def __init__(self, sc, name="default", nodeid=None, action=1, target=1, args={}):
        """
        Creates a new Synth with given supercollider instance, name and a dict of arguments to the synth. \n
        Example: stk.Synth(sc=sc, args={"dur": 1, "freq": 400}, name="\s1")
        """
        self.name = name
        self.args = args
        self.sc = sc
        self.nodeid = nodeid if nodeid is not None else sc.nextNodeID()
        self.action = action
        self.target = target
        flatten_dict = [val for sublist in [list((k, v)) for k, v in args.items()] for val in sublist]
        self.sc.msg("/s_new", [name, self.nodeid, action, target] + flatten_dict)
        self.pause_status = False

    def run(self, flag=True):
        """
        En-/Disable synth running
        """
        self.sc.msg("/n_run", [self.nodeid, 0 if flag is False else 1])
        self.pause_status = not flag
        return self

    def pause(self, flag=None):
        """
        Pause a synth, or play it, if synth is allready paused
        """
        self.run(flag if flag is not None else self.pause_status)
        return self

    def free(self):
        """
        Deletes a synth/ stop it
        """
        self.sc.msg("/n_free", [self.nodeid])
        return self

    def stop(self):
        self.free()
        self.restart()

    def restart(self):
        """
        Recreates a synth - you can call this method after you free the synth, or the synth was played completely.
        Attention: Here you create an identical synth! Same synth node etc. - use this method only, if your synth is freeed before!
        """
        flatten_dict = [val for sublist in [list((k, v)) for k, v in self.args.items()] for val in sublist]
        self.sc.msg("/s_new", [self.name, self.nodeid, self.action, self.target] + flatten_dict)
        return self

    def set(self, key, value):
        """
        Set a control variable for synth after defining it
        """
        self.args[key] = value
        self.sc.msg("/n_set", [self.nodeid, key, value])
        return self

    def __del__(self):
        self.free()


class SynthDef:
    def __init__(self, sc, name="", definition=""):
        """
        Create a dynamic synth definition in sc.

        Parameters
        ----------
        sc: SC object
            SC instance where the synthdef should be created
        name: string
            default name of the synthdef creation. The naming convention will be name+int, where int is the amount of
            already created synths of this definition
        definition: string
            Pass the default synthdef definition here. Flexible content should be in double
            brackets ("...{{flexibleContent}}..."). This flexible content, you can dynamic replace with set_context()
        """
        self.sc = sc
        self.definition = definition
        self.name = name
        self.current_def = definition
        # dict of all already defined synthdefs with this root-defintion (key=name, value=definition)
        self.defined_instances = {}

    def reset(self):
        """
        Reset the current synthdef configuration to the self.definition value. After this you can restart your
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
        This method will replace a given key (format: "...{{key}}...") in the synthdef definition with the given value.

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
        Set multiple values at onces when you give a dictionary. Because dictionaries are unsorted, keep in mind, that
        the order is sometimes ignored in this method.

        Parameters
        ----------
        dictionary: dict
            (k,v) tuple dict, while k is the searchpattern and v is the replacement

        Returns
        -------
        self : object of type SynthDef
            the SynthDef object
        """
        for (k, v) in dictionary:
            self.set_context(k, v)
        return self

    def unset_remaining(self):
        """
        This method will remove all existing placeholders in the current def. You can use this at the end of definition
        to make sure, that your definition is clean. Hint: This method will not remove pyvars

        Returns
        -------
        self : object of type SynthDef
            the SynthDef object

        """
        self.current_def = re.sub(r"{{[^}]+}}", "", self.current_def)
        return self

    def create(self, pyvars={}):
        """
        This method will create the current_def as a sc synthDef. It will block until sc has created the synthdef.
        If a synth with the same definition was already in sc, this method will only return the name

        Parameters
        ----------
        pyvars: dict
            SC pyvars dict, to modify the synthdef command while executing it.

        Returns
        -------
        string: Name of the synthdef
        """

        # Check if a synth with the same definition is already defined -> use this
        if self.current_def in self.defined_instances.values():
            return list(self.defined_instances.keys())[list(self.defined_instances.values()).index(self.current_def)]

        name = self.name + str(len(self.defined_instances))

        # Create new synthDef
        self.sc.cmd(f"""SynthDef("{name}", {self.current_def}).add();""", pyvars=pyvars)
        self.defined_instances[name] = self.current_def
        # ToDo: Wait for release of: self.sc.osc.sync()
        return name

    def create_and_reset(self, pyvars={}):
        self.create(pyvars)
        self.reset()

    def free(self, name: str):
        """

        Parameters
        ----------
        name: str
            Name of the SynthDef, which should be freed. The SynthDef must not be created by the current SynthDef object

        Returns
        -------
        self : object of type SynthDef
            the SynthDef object

        """
        self.sc.msg("/d_free", [name])

        # Update defined instances. Important: Don't delete the entry! The naming convention for synthdefs is based on
        # the count of defined_instances, so a deleted key could override an existing synthdef.
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

