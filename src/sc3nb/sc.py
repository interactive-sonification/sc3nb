"""Contains classes enabling the easy communication with SuperCollider
within jupyter notebooks
"""

import logging
import warnings
from typing import Optional, Sequence

from IPython import get_ipython

import sc3nb.magics as magics
from sc3nb.process_handling import ALLOWED_PARENTS, ProcessTimeout
from sc3nb.sc_objects.server import SCServer, ServerOptions
from sc3nb.sclang import SCLang

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())


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
) -> "SC":
    """Inits SuperCollider (scsynth, sclang) and registers Jupyter magics

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
        If True register magics to Jupyter, by default True
    scsynth_options : Optional[ServerOptions], optional
        Options for the server, by default None
    with_blip : bool, optional
            make a sound when booted, by default True
    console_logging : bool, optional
        If True write scsynth/sclang output to console, by default True
    allowed_parents : Sequence[str], optional
        Names of parents that are allowed for other instances of
        sclang/scsynth processes, by default ALLOWED_PARENTS

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
            with_blib=with_blip,
            console_logging=console_logging,
            allowed_parents=allowed_parents,
        )
    else:
        _LOGGER.info("SC already started")
        if start_sclang:
            SC.get_default().start_sclang(
                sclang_path=sclang_path, allowed_parents=allowed_parents
            )
        if start_server:
            SC.get_default().start_server(
                scsynth_options=scsynth_options,
                scsynth_path=scsynth_path,
                allowed_parents=allowed_parents,
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
    with_blib : bool, optional
        Make a sound when booted, by default True.
    console_logging : bool, optional
        If True write scsynth/sclang output to console, by default True.
    allowed_parents : Sequence[str], optional
        Names of parents that are allowed for other instances of
        sclang/scsynth processes, by default ALLOWED_PARENTS.
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
                " or provide a sclang/server directly."
            )

    def __init__(
        self,
        start_server: bool = True,
        scsynth_path: Optional[str] = None,
        start_sclang: bool = True,
        sclang_path: Optional[str] = None,
        scsynth_options: Optional[ServerOptions] = None,
        with_blib: bool = True,
        console_logging: bool = True,
        allowed_parents: Sequence[str] = ALLOWED_PARENTS,
    ):
        if SC.default is None:
            SC.default = self
        self._console_logging = console_logging
        self._server = None
        self._sclang = None
        if start_sclang:
            self.start_sclang(
                sclang_path=sclang_path,
                console_logging=self._console_logging,
                allowed_parents=allowed_parents,
            )
        if start_server:
            self.start_server(
                scsynth_path=scsynth_path,
                scsynth_options=scsynth_options,
                console_logging=self._console_logging,
                with_blip=with_blib,
                allowed_parents=allowed_parents,
            )

    def start_sclang(
        self,
        sclang_path: Optional[str] = None,
        console_logging: bool = True,
        allowed_parents: Sequence[str] = ALLOWED_PARENTS,
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
        """
        if self._sclang is None:
            self._sclang = SCLang()
            try:
                self._sclang.start(
                    sclang_path=sclang_path,
                    console_logging=console_logging,
                    allowed_parents=allowed_parents,
                )
            except ProcessTimeout:
                self._sclang = None
                warnings.warn("starting sclang failed")
                raise
            else:
                if self._server is not None:
                    self._sclang.connect_to_server(self._server)
        else:
            _LOGGER.info("sclang already started")

    def start_server(
        self,
        scsynth_options: Optional[ServerOptions] = None,
        scsynth_path: Optional[str] = None,
        console_logging: bool = True,
        with_blip: bool = True,
        allowed_parents: Sequence[str] = ALLOWED_PARENTS,
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
        """
        if self._server is None:
            self._server = SCServer(options=scsynth_options)
            try:
                self._server.boot(
                    scsynth_path=scsynth_path,
                    console_logging=console_logging,
                    allowed_parents=allowed_parents,
                    with_blip=with_blip,
                )
                if self._sclang is not None:
                    self._sclang.connect_to_server(self._server)
            except ProcessTimeout:
                self._server = None
                warnings.warn("starting scsynth failed")
                raise
        else:
            _LOGGER.info("scsynth already started")

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

    def exit(self) -> None:
        """Closes SuperCollider and shuts down server"""
        if (
            self._server is not None
            and self._server.has_booted
            and self._server.is_local
        ):
            self._server.quit()
            self._server = None
        if self._sclang is not None:
            self._sclang.kill()
            self._sclang = None
        if self is SC.default:
            SC.default = None
