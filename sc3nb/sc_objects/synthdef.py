"""Module to for using SuperCollider SynthDefs and Synths in Python"""

import re

import sc3nb

class SynthDef:
    """Wrapper for SuperCollider SynthDef"""

    synth_descs = {}


    @classmethod # TODO add this to a SynthDesc class to the server?
    def get_desc(cls, name):
        if name in cls.synth_descs:
            return cls.synth_descs[name]
        return cls.synth_descs.setdefault(name, sc3nb.SC.default.lang.get_synth_desc(name))


    def __init__(self, name, definition, sc=None):
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
        self.sc = sc or sc3nb.SC.default
        self.definition = definition
        self.name = name
        self.current_def = definition

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

    def set_context(self, searchpattern: str, value):
        """
        This method will replace a given key (format: "...{{key}}...") in the
        synthdef definition with the given value.

        Parameters
        ----------
        searchpattern: string
                search pattern in the current_def string
        value: string or something with can parsed to string
                Replacement of search pattern

        Returns
        -------
        self : object of type SynthDef
            the SynthDef object
        """
        self.current_def = self.current_def.replace("{{"+searchpattern+"}}", str(value))
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

    def add(self, pyvars=None, name=None):
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
        if name is None:
            name = self.name
        else:
            self.name = name

        if pyvars is None:
            pyvars = sc3nb.sclang.parse_pyvars(self.current_def)

        # Create new SynthDef add it to SynthDescLib and get bytes
        synth_def_blob = self.sc.lang.cmdg(f"""
            r.tmpSynthDef = SynthDef("{name}", {self.current_def});
            SynthDescLib.global.add(r.tmpSynthDef.asSynthDesc);
            r.tmpSynthDef.asBytes();""", pyvars=pyvars)
        self.sc.server.msg("/d_recv", synth_def_blob)
        return self.name

    def free(self):
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
        self.sc.server.msg("/d_free", [self.name])
        return self

    def __repr__(self):
        return f'SynthDef("{self.name}",{self.current_def})'
