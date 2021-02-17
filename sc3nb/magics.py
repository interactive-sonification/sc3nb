"""This Module adds the Jupyter specialties as Magics and Keyboard Shortcuts"""
import sys
import re
import warnings

from IPython.core.magic import Magics, magics_class, line_cell_magic

import sc3nb

def load_ipython_extension(ipython):
    ipython.register_magics(SC3Magics)
    add_shortcut(ipython)

def add_shortcut(ipython, shortcut = None):
    try:
        if sys.platform == "darwin":
            shortcut = 'cmd-.'
        elif sys.platform in ["linux", "linux2", "win32"]:
            shortcut = 'Ctrl-.'
        else:
            warnings.warn(f"Unable to add shortcut for platform '{sys.platform}'")
        if shortcut is not None:
            ipython.run_cell_magic(
                'javascript',
                '',
                f'''if (typeof Jupyter !== 'undefined') {{
                        Jupyter.keyboard_manager.command_shortcuts.add_shortcut(
                        \'{shortcut}\', {{
                        help : \'Free all nodes on SC server\',
                        help_index : \'zz\',
                        handler : function (event) {{
                            IPython.notebook.kernel.execute(
                                "import sc3nb; sc3nb.SC.default.server.free_all(root=True)"
                            )
                            return true;}}
                        }});
                    }}''')
    except AttributeError:
        pass


@magics_class
class SC3Magics(Magics):
    """Jupyter magics for SC class
    """

    @line_cell_magic
    def sc(self, line='', cell=None):
        """Execute SuperCollider code via magic

        Keyword Arguments:
            line {str} -- Line of SuperCollider code (default: {''})
            cell {str} -- Cell of SuperCollider code (default: {None})
        """
        if cell is None:
            cmdstr = line
        else:
            cmdstr = cell
        pyvars = self._parse_pyvars(cmdstr)
        return sc3nb.SC.default.lang.cmd(cmdstr, pyvars=pyvars)

    @line_cell_magic
    def scv(self, line='', cell=None):
        """Execute SuperCollider code with verbose output

        Keyword Arguments:
            line {str} -- Line of SuperCollider code (default: {''})
            cell {str} -- Cell of SuperCollider code (default: {None})
        """
        if cell is None:
            cmdstr = line
        else:
            cmdstr = cell
        pyvars = self._parse_pyvars(cmdstr)
        return sc3nb.SC.default.lang.cmdv(cmdstr, pyvars=pyvars)

    @line_cell_magic
    def scg(self, line='', cell=None):
        """Execute SuperCollider code returning output

        Keyword Arguments:
            line {str} -- Line of SuperCollider code (default: {''})
            cell {str} -- Cell of SuperCollider code (default: {None})

        Returns:
            {*} -- Output from SuperCollider code, not
                   all SC types supported, see
                   pythonosc.osc_message.Message for list
                   of supported types
        """
        if cell is None:
            cmdstr = line
        else:
            cmdstr = cell
        pyvars = self._parse_pyvars(cmdstr)
        return sc3nb.SC.default.lang.cmdg(cmdstr, pyvars=pyvars)

    @line_cell_magic
    def scgv(self, line='', cell=None):
        """Execute SuperCollider code returning output

        Keyword Arguments:
            line {str} -- Line of SuperCollider code (default: {''})
            cell {str} -- Cell of SuperCollider code (default: {None})

        Returns:
            {*} -- Output from SuperCollider code, not
                   all SC types supported, see
                   pythonosc.osc_message.Message for list
                   of supported types
        """
        if cell is None:
            cmdstr = line
        else:
            cmdstr = cell
        pyvars = self._parse_pyvars(cmdstr)
        return sc3nb.SC.default.lang.cmdv(cmdstr, pyvars=pyvars)

    def _parse_pyvars(self, cmdstr):
        """Parses SuperCollider code grabbing python variables
        and their values
        """
        user_ns = self.shell.user_ns

        matches = re.findall(r'\s*\^[A-Za-z_]\w*\s*', cmdstr)
        pyvars = {match.split('^')[1].strip(): None for match in matches}
        for pyvar in pyvars:
            if pyvar in user_ns:
                pyvars[pyvar] = user_ns[pyvar]
            else:
                raise NameError('name \'{}\' is not defined'.format(pyvar))

        return pyvars
