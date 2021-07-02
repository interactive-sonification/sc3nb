"""Contains classes enabling the easy communication with SuperCollider
within jupyter notebooks
"""

import logging
from typing import Optional, Sequence

from IPython import get_ipython

import sc3nb.magics as magics
from sc3nb.process_handling import ALLOWED_PARENTS
from sc3nb.sc_objects.server import SCServer, ServerOptions
from sc3nb.sclang import SCLang

_LOGGER = logging.getLogger(__name__)


def startup(
    start_server: bool = True,
    scsynth_path: Optional[str] = None,
    start_sclang: bool = True,
    sclang_path: Optional[str] = None,
    magic: bool = True,
    scsynth_options: Optional[ServerOptions] = None,
    with_blip: bool = True,
    console_logging: bool = True,
    allowed_parents: Sequence[str] = ALLOWED_PARENTS,
    timeout: float = 10,
) -> "SC":
    """Inits SuperCollider (scsynth, sclang) and registers ipython magics

    Parameters
    ----------
    start_server : bool, optional
        If True boot scsynth, by default True
    scsynth_path : Optional[str], optional
        Path of scscynth executable, by default None
    start_sclang : bool, optional
        If True start sclang, by default True
    sclang_path : Optional[str], optional
        Path of sclang executable, by default None
    magic : bool, optional
        If True register magics to ipython, by default True
    scsynth_options : Optional[ServerOptions], optional
        Options for the server, by default None
    with_blip : bool, optional
            make a sound when booted, by default True
    console_logging : bool, optional
        If True write scsynth/sclang output to console, by default True
    allowed_parents : Sequence[str], optional
        Names of parents that are allowed for other instances of
        sclang/scsynth processes, by default ALLOWED_PARENTS
    timeout : float, optional
        timeout in seconds for starting the executable, by default 10

    Returns
    -------
    SC
        SuperCollider Interface class.
    """
    if magic:
        ipy = get_ipython()
        if ipy is not None:
            magics.load_ipython_extension(ipy)

    if SC.default is None:
        SC.default = SC(
            start_server=start_server,
            scsynth_path=scsynth_path,
            start_sclang=start_sclang,
            sclang_path=sclang_path,
            scsynth_options=scsynth_options,
            with_blip=with_blip,
            console_logging=console_logging,
            allowed_parents=allowed_parents,
            timeout=timeout,
        )
    else:
        _LOGGER.warning("SC already started")
        if start_sclang:
            SC.get_default().start_sclang(
                sclang_path=sclang_path,
                allowed_parents=allowed_parents,
                timeout=timeout,
            )
        if start_server:
            SC.get_default().start_server(
                scsynth_options=scsynth_options,
                scsynth_path=scsynth_path,
                allowed_parents=allowed_parents,
                timeout=timeout,
            )
    return SC.default


class SC:
    """Create a SuperCollider Wrapper object.

    Parameters
    ----------
    start_server : bool, optional
        If True boot scsynth, by default True.
    scsynth_path : Optional[str], optional
        Path of scscynth executable, by default None.
    start_sclang : bool, optional
        If True start sclang, by default True.
    sclang_path : Optional[str], optional
        Path of sclang executable, by default None.
    scsynth_options : Optional[ServerOptions], optional
        Options for the server, by default None.
    with_blip : bool, optional
        Make a sound when booted, by default True.
    console_logging : bool, optional
        If True write scsynth/sclang output to console, by default True.
    allowed_parents : Sequence[str], optional
        Names of parents that are allowed for other instances of
        sclang/scsynth processes, by default ALLOWED_PARENTS.
    timeout : float, optional
        timeout in seconds for starting the executables, by default 5
    """

    default: Optional["SC"] = None
    """Default SC instance.

    This will be used by all SuperCollider objects if no SC/server/lang is specified.
    """

    @classmethod
    def get_default(cls) -> "SC":
        """Get the default SC instance

        Returns
        -------
        SC
            default SC instance

        Raises
        ------
        RuntimeError
            If there is no default SC instance.
        """
        if cls.default is not None:
            return cls.default
        else:
            raise RuntimeError(
                "You need to start a SuperCollider SC instance first"
                " or provide an sclang/server directly."
            )

    def __init__(
        self,
        *,
        start_server: bool = True,
        scsynth_path: Optional[str] = None,
        start_sclang: bool = True,
        sclang_path: Optional[str] = None,
        scsynth_options: Optional[ServerOptions] = None,
        with_blip: bool = True,
        console_logging: bool = True,
        allowed_parents: Sequence[str] = ALLOWED_PARENTS,
        timeout: float = 5,
    ):
        if SC.default is None:
            SC.default = self
        self._console_logging = console_logging
        self._server = None
        self._sclang = None
        try:
            if start_sclang:
                self.start_sclang(
                    sclang_path=sclang_path,
                    console_logging=self._console_logging,
                    allowed_parents=allowed_parents,
                    timeout=timeout,
                )
            if start_server:
                self.start_server(
                    scsynth_path=scsynth_path,
                    scsynth_options=scsynth_options,
                    console_logging=self._console_logging,
                    with_blip=with_blip,
                    allowed_parents=allowed_parents,
                    timeout=timeout,
                )
        except Exception:
            if SC.default is self:
                SC.default = None
            raise

    def start_sclang(
        self,
        sclang_path: Optional[str] = None,
        console_logging: bool = True,
        allowed_parents: Sequence[str] = ALLOWED_PARENTS,
        timeout: float = 5,
    ):
        """Start this SuperCollider language

        Parameters
        ----------
        sclang_path : Optional[str], optional
            Path of sclang executable, by default None
        console_logging : bool, optional
            If True write scsynth/sclang output to console, by default True
        allowed_parents : Sequence[str], optional
            Names of parents that are allowed for other instances of
            sclang/scsynth processes, by default ALLOWED_PARENTS
        timeout : float, optional
            timeout in seconds for starting the executable, by default 5
        """
        if self._sclang is None:
            self._sclang = SCLang()
            try:
                self._sclang.start(
                    sclang_path=sclang_path,
                    console_logging=console_logging,
                    allowed_parents=allowed_parents,
                    timeout=timeout,
                )
            except Exception as excep:
                self._sclang = None
                raise RuntimeError(f"Starting sclang failed - {excep}") from excep
            else:
                self._try_to_connect()
        else:
            _LOGGER.warning("sclang already started")
        if SC.default is None:
            SC.default = self

    def start_server(
        self,
        scsynth_options: Optional[ServerOptions] = None,
        scsynth_path: Optional[str] = None,
        console_logging: bool = True,
        with_blip: bool = True,
        allowed_parents: Sequence[str] = ALLOWED_PARENTS,
        timeout: float = 5,
    ):
        """Start this SuperCollider server

        Parameters
        ----------
        scsynth_options : Optional[ServerOptions], optional
            Options for the server, by default None
        scsynth_path : Optional[str], optional
            Path of scscynth executable, by default None
        console_logging : bool, optional
            If True write scsynth/sclang output to console, by default True
        with_blip : bool, optional
            make a sound when booted, by default True
        allowed_parents : Sequence[str], optional
            Names of parents that are allowed for other instances of
            sclang/scsynth processes, by default ALLOWED_PARENTS
        timeout : float, optional
            timeout in seconds for starting the executable, by default 5
        """
        if self._server is None:
            self._server = SCServer(options=scsynth_options)
            try:
                self._server.boot(
                    scsynth_path=scsynth_path,
                    console_logging=console_logging,
                    allowed_parents=allowed_parents,
                    with_blip=with_blip,
                    timeout=timeout,
                )
            except Exception as excep:
                self._server = None
                raise RuntimeError(f"Starting scsynth failed - {excep}") from excep
            else:
                self._try_to_connect()
        else:
            _LOGGER.warning("scsynth already started")
        if SC.default is None:
            SC.default = self

    def _try_to_connect(self):
        if self._sclang is not None and self._server is not None:
            try:
                self._sclang.connect_to_server(self._server)
            except Exception as excep:
                raise RuntimeError(
                    f"connecting {self._sclang} to {self._server} failed"
                ) from excep

    @property
    def server(self) -> SCServer:
        """This SuperCollider server object"""
        if self._server is not None:
            return self._server
        else:
            raise RuntimeError("You need to start the SuperCollider Server first")

    @property
    def lang(self) -> SCLang:
        """This SuperCollider language object"""
        if self._sclang is not None:
            return self._sclang
        else:
            raise RuntimeError(
                "You need to start the SuperCollider Language (sclang) first"
            )

    @property
    def console_logging(self):
        """True if console logging enabled"""
        return self._console_logging

    @console_logging.setter
    def console_logging(self, value):
        if self._server is not None:
            self._server.process.console_logging = value
        if self._sclang is not None:
            self._sclang.process.console_logging = value

    def __del__(self):
        self.exit()

    def __repr__(self) -> str:
        server = self._server if self._server is not None else "SCServer not started"
        lang = self._sclang if self._sclang is not None else "SCLang not started"
        return f"<SC {server},\n    {lang}>"

    def exit(self) -> None:
        """Closes SuperCollider and shuts down server"""
        try:
            if self._server is not None:
                self._server.quit()
            if self._sclang is not None:
                self._sclang.kill()
        finally:
            self._server = None
            self._sclang = None
            if self is SC.default:
                SC.default = None
