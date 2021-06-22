"""This module adds the Jupyter specialties such as Magics and Keyboard Shortcuts"""
import re
import sys
import warnings
from typing import Any, Dict

from IPython.core.magic import Magics, line_cell_magic, magics_class

import sc3nb


def load_ipython_extension(ipython) -> None:
    """Function that is called when Jupyter loads this as extension (%load_ext sc3nb)

    Parameters
    ----------
    ipython : IPython
        IPython object
    """
    ipython.register_magics(SC3Magics)
    add_shortcut(ipython)


def add_shortcut(ipython, shortcut: str = None) -> None:
    """Add the server 'free all' shortcut.

    Parameters
    ----------
    ipython : IPython
        IPython object
    shortcut : str, optional
        shortcut for 'free all', by default it is "cmd-." or "Ctrl-."
    """
    try:
        if shortcut is None:
            if sys.platform == "darwin":
                shortcut = "cmd-."
            elif sys.platform in ["linux", "linux2", "win32"]:
                shortcut = "Ctrl-."
            else:
                warnings.warn(f"Unable to add shortcut for platform '{sys.platform}'")
        if shortcut is not None:
            ipython.run_cell_magic(
                "javascript",
                "",
                f"""if (typeof Jupyter !== 'undefined') {{
                        Jupyter.keyboard_manager.command_shortcuts.add_shortcut(
                        \'{shortcut}\', {{
                        help : \'Free all nodes on SC server\',
                        help_index : \'zz\',
                        handler : function (event) {{
                            IPython.notebook.kernel.execute(
                                "import sc3nb; sc3nb.SC.get_default().server.free_all(root=True)"
                            )
                            return true;}}
                        }});
                    }}""",
            )
    except AttributeError:
        pass


@magics_class
class SC3Magics(Magics):
    """IPython magics for SC class"""

    @line_cell_magic
    def sc(self, line="", cell=None):
        """Execute SuperCollider code via magic

        Parameters
        ----------
        line : str, optional
            Line of SuperCollider code, by default ''
        cell : str, optional
            Cell of SuperCollider code , by default None

        Returns
        -------
        Unknown
            cmd result
        """
        cmdstr = line if cell is None else cell
        pyvars = self._parse_pyvars(cmdstr)
        return sc3nb.SC.get_default().lang.cmd(cmdstr, pyvars=pyvars)

    @line_cell_magic
    def scv(self, line="", cell=None):
        """Execute SuperCollider code with verbose output

        Parameters
        ----------
        line : str, optional
            Line of SuperCollider code, by default ''
        cell : str, optional
            Cell of SuperCollider code , by default None

        Returns
        -------
        Unknown
            cmd result
        """
        cmdstr = line if cell is None else cell
        pyvars = self._parse_pyvars(cmdstr)
        return sc3nb.SC.get_default().lang.cmdv(cmdstr, pyvars=pyvars)

    @line_cell_magic
    def scs(self, line="", cell=None):
        """Execute SuperCollider code silently (verbose==False)

        Parameters
        ----------
        line : str, optional
            Line of SuperCollider code, by default ''
        cell : str, optional
            Cell of SuperCollider code , by default None

        Returns
        -------
        Unknown
            cmd result
        """
        cmdstr = line if cell is None else cell
        pyvars = self._parse_pyvars(cmdstr)
        return sc3nb.SC.get_default().lang.cmds(cmdstr, pyvars=pyvars)

    @line_cell_magic
    def scg(self, line="", cell=None):
        """Execute SuperCollider code returning output

        Parameters
        ----------
        line : str, optional
            Line of SuperCollider code, by default ''
        cell : str, optional
            Cell of SuperCollider code , by default None

        Returns
        -------
        Unknown
            cmd result
            Output from SuperCollider code, not
            all SC types supported, see
            pythonosc.osc_message.Message for list
            of supported types
        """
        cmdstr = line if cell is None else cell
        pyvars = self._parse_pyvars(cmdstr)
        return sc3nb.SC.get_default().lang.cmdg(cmdstr, pyvars=pyvars)

    @line_cell_magic
    def scgv(self, line="", cell=None):
        """Execute SuperCollider code returning output

        Parameters
        ----------
        line : str, optional
            Line of SuperCollider code, by default ''
        cell : str, optional
            Cell of SuperCollider code , by default None

        Returns
        -------
        Unknown
            cmd result
            Output from SuperCollider code, not
            all SC types supported, see
            pythonosc.osc_message.Message for list
            of supported types
        """
        cmdstr = line if cell is None else cell
        pyvars = self._parse_pyvars(cmdstr)
        return sc3nb.SC.get_default().lang.cmdg(cmdstr, pyvars=pyvars, verbose=True)

    @line_cell_magic
    def scgs(self, line="", cell=None):
        """Execute SuperCollider code returning output

        Parameters
        ----------
        line : str, optional
            Line of SuperCollider code, by default ''
        cell : str, optional
            Cell of SuperCollider code , by default None

        Returns
        -------
        Unknown
            cmd result
            Output from SuperCollider code, not
            all SC types supported, see
            pythonosc.osc_message.Message for list
            of supported types
        """
        cmdstr = line if cell is None else cell
        pyvars = self._parse_pyvars(cmdstr)
        return sc3nb.SC.get_default().lang.cmdg(cmdstr, pyvars=pyvars, verbose=False)

    def _parse_pyvars(self, code: str) -> Dict[str, Any]:
        """Parses SuperCollider code for python variables and their values

        Parameters
        ----------
        code : str
            SuperCollider code snippet

        Returns
        -------
        Dict[str, Any]
            Dict with variable names and their values.

        Raises
        ------
        NameError
            If pyvar injection value can't be found.
        """
        user_ns = self.shell.user_ns

        matches = re.findall(r"\s*\^[A-Za-z_]\w*\s*", code)
        pyvars = {match.split("^")[1].strip(): None for match in matches}
        for pyvar in pyvars:
            if pyvar in user_ns:
                pyvars[pyvar] = user_ns[pyvar]
            else:
                raise NameError("name '{}' is not defined".format(pyvar))

        return pyvars
