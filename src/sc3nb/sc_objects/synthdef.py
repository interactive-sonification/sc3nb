"""Module to for using SuperCollider SynthDefs and Synths in Python"""

import re
import sys
import warnings
from enum import Enum, unique
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

if sys.version_info < (3, 9):
    # `importlib.resources` backported to PY<37 as `importlib_resources`.
    import importlib_resources as libresources
else:
    # only PY>=39 `importlib.resources` offers .files.
    import importlib.resources as libresources

import sc3nb
import sc3nb.resources
from sc3nb.util import parse_pyvars, replace_vars

if TYPE_CHECKING:
    from sc3nb.sc import SC
    from sc3nb.sc_objects.server import SCServer
    from sc3nb.sclang import SynthArgument


@unique
class SynthDefinitionCommand(str, Enum):
    """OSC Commands for Synth Definitions"""

    RECV = "/d_recv"
    LOAD = "/d_load"
    LOAD_DIR = "/d_loadDir"
    FREE = "/d_free"


class SynthDef:
    """Wrapper for SuperCollider SynthDef"""

    synth_descs = {}

    @classmethod
    def get_description(cls, name: str) -> Optional[Dict[str, "SynthArgument"]]:
        """Get Synth description

        Parameters
        ----------
        name : str
            name of SynthDef

        Returns
        -------
        Dict
            dict with SynthArguments
        """
        if name in cls.synth_descs:
            return cls.synth_descs[name]
        try:
            synth_desc = sc3nb.SC.get_default().lang.get_synth_description(name)
        except RuntimeError:
            synth_desc = None

        if synth_desc is not None:
            cls.synth_descs[name] = synth_desc
        else:
            try:
                sc3nb.SC.get_default().lang
            except RuntimeError:
                sclang_text = "sclang is not running."
            else:
                sclang_text = "sclang does not know this SynthDef"
            warnings.warn(f"SynthDesc '{name}' is unknown. {sclang_text}")
        return synth_desc

    @classmethod
    def send(
        cls,
        synthdef_bytes: bytes,
        server: Optional["SCServer"] = None,
    ):
        """Send a SynthDef as bytes.

        Parameters
        ----------
        synthdef_bytes : bytes
            SynthDef bytes
        wait : bool
            If True wait for server reply.
        server : SCServer, optional
            Server instance that gets the SynthDefs,
            by default use the SC default server
        """
        if server is None:
            server = sc3nb.SC.get_default().server
        server.msg(
            SynthDefinitionCommand.RECV,
            synthdef_bytes,
            await_reply=True,
            bundle=True,
        )

    @classmethod
    def load(
        cls,
        synthdef_path: str,
        server: Optional["SCServer"] = None,
    ):
        """Load SynthDef file at path.

        Parameters
        ----------
        synthdef_path : str
            Path with the SynthDefs
        server : SCServer, optional
            Server that gets the SynthDefs,
            by default use the SC default server
        """
        if server is None:
            server = sc3nb.SC.get_default().server
        server.msg(
            SynthDefinitionCommand.LOAD,
            synthdef_path,
            await_reply=True,
            bundle=True,
        )

    @classmethod
    def load_dir(
        cls,
        synthdef_dir: Optional[str] = None,
        completion_msg: Optional[bytes] = None,
        server: Optional["SCServer"] = None,
    ):
        """Load all SynthDefs from directory.

        Parameters
        ----------
        synthdef_dir : str, optional
            directory with SynthDefs, by default sc3nb default SynthDefs
        completion_msg : bytes, optional
            Message to be executed by the server when loaded, by default None
        server : SCServer, optional
            Server that gets the SynthDefs,
            by default use the SC default server
        """
        if server is None:
            server = sc3nb.SC.get_default().server

        def _load_synthdefs(path):
            cmd_args: List[Union[str, bytes]] = [path.as_posix()]
            if completion_msg is not None:
                cmd_args.append(completion_msg)
            server.msg(
                SynthDefinitionCommand.LOAD_DIR,
                cmd_args,
                await_reply=True,
                bundle=True,
            )

        if synthdef_dir is None:
            ref = libresources.files(sc3nb.resources) / "synthdefs"
            with libresources.as_file(ref) as path:
                _load_synthdefs(path)
        else:
            path = Path(synthdef_dir)
            if path.exists() and path.is_dir():
                _load_synthdefs(path)
            else:
                raise ValueError(f"Provided path {path} does not exist or is not a dir")

    def __init__(self, name: str, definition: str, sc: Optional["SC"] = None) -> None:
        """Create a dynamic synth definition in sc.

        Parameters
        ----------
        name : string
            default name of the synthdef creation.
            The naming convention will be name+int, where int is the amount of
            already created synths of this definition
        definition : string
            Pass the default synthdef definition here. Flexible content
            should be in double brackets ("...{{flexibleContent}}...").
            This flexible content, you can dynamic replace with set_context()
        sc : SC object
            SC instance where the synthdef should be created,
            by default use the default SC instance
        """
        self.sc = sc
        self.definition = definition
        self.name = name
        self.current_def = definition

    def reset(self) -> "SynthDef":
        """Reset the current synthdef configuration to the self.definition value.

        After this you can restart your
        configuration with the same root definition

        Returns
        -------
        object of type SynthDef
            the SynthDef object
        """
        self.current_def = self.definition
        return self

    def set_context(self, searchpattern: str, value) -> "SynthDef":
        """Set context in SynthDef.

        This method will replace a given key (format: "...{{key}}...") in the
        synthdef definition with the given value.

        Parameters
        ----------
        searchpattern : string
            search pattern in the current_def string
        value : string or something with can parsed to string
            Replacement of search pattern

        Returns
        -------
        self : object of type SynthDef
            the SynthDef object
        """
        self.current_def = self.current_def.replace(
            "{{" + searchpattern + "}}", str(value)
        )
        return self

    def set_contexts(self, dictionary: Dict[str, Any]) -> "SynthDef":
        """Set multiple values at onces when you give a dictionary.

        Because dictionaries are unsorted, keep in mind, that
        the order is sometimes ignored in this method.

        Parameters
        ----------
        dictionary : dict
            {searchpattern: replacement}

        Returns
        -------
        self : object of type SynthDef
            the SynthDef object
        """
        for (searchpattern, replacement) in dictionary.items():
            self.set_context(searchpattern, replacement)
        return self

    def unset_remaining(self) -> "SynthDef":
        """This method will remove all existing placeholders in the current def.

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

    def add(
        self,
        pyvars=None,
        name: Optional[str] = None,
        server: Optional["SCServer"] = None,
    ) -> str:
        """This method will add the current_def to SuperCollider.s

        If a synth with the same definition was already in sc, this method
        will only return the name.

        Parameters
        ----------
        pyvars : dict
            SC pyvars dict, to inject python variables
        name : str, optional
            name which this SynthDef will get
        server : SCServer, optional
            Server where this SynthDef will be send to,
            by default use the SC default server

        Returns
        -------
        str
            Name of the SynthDef
        """
        if name is None:
            name = self.name
        else:
            self.name = name

        if pyvars is None:
            pyvars = sc3nb.sclang.parse_pyvars(self.current_def)

        # TODO should check if there is context/pyvars that can't be set

        # Create new SynthDef add it to SynthDescLib and get bytes
        if self.sc is None:
            self.sc = sc3nb.SC.get_default()
        synth_def_blob, output = self.sc.lang.cmd(
            f"""
            "sc3nb - Creating SynthDef {name}".postln;
            r.tmpSynthDef = SynthDef("{name}", {self.current_def});
            SynthDescLib.global.add(r.tmpSynthDef.asSynthDesc);
            r.tmpSynthDef.asBytes();""",
            pyvars=pyvars,
            verbose=False,
            get_result=True,
            get_output=True,
        )
        if synth_def_blob == 0:
            print(output)
            raise RuntimeError(f"Adding SynthDef failed. - {output}")
        else:
            if server is not None:
                server.send_synthdef(synth_def_blob)
            else:
                self.sc.server.send_synthdef(synth_def_blob)
            return self.name

    def free(self) -> "SynthDef":
        """Free this SynthDef from the server.

        Returns
        -------
        self : object of type SynthDef
            the SynthDef object
        """
        if self.sc is None:
            self.sc = sc3nb.SC.get_default()
        self.sc.server.msg(SynthDefinitionCommand.FREE, [self.name], bundle=True)
        return self

    def __repr__(self):
        try:
            pyvars = parse_pyvars(self.current_def)
        except NameError:
            current_def = self.current_def
        else:
            current_def = replace_vars(self.current_def, pyvars)
        return f"SynthDef('{self.name}', {current_def})"
