""" Module for process handling. """

import atexit
import glob
import logging
import os
import platform
import re
import subprocess
import threading
import time
import warnings
from queue import Empty, Queue
from typing import Optional, Sequence

import psutil

_LOGGER = logging.getLogger(__name__)


ANSI_ESCAPE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
ALLOWED_PARENTS = ("scide", "python", "tox")


def find_executable(
    executable: str, search_path: str = None, add_to_path: bool = False
):
    """Looks for executable in os $PATH or specified path

    Parameters
    ----------
    executable : str
        Executable to be found
    search_path : str, optional
        Path at which to look for, by default None
    add_to_path : bool, optional
        Wether to add the provided path to os $PATH or not, by default False

    Returns
    -------
    str
        Full path to executable

    Raises
    ------
    FileNotFoundError
        Raised if executable cannot be found
    """
    paths = os.environ["PATH"].split(os.pathsep)

    if search_path is not None:
        head, tail = os.path.split(search_path)
        if executable == os.path.splitext(tail):
            search_path = head
        if search_path not in os.environ["PATH"] and add_to_path:
            os.environ["PATH"] += os.pathsep + search_path
        paths.insert(0, search_path)

    if platform.system() == "Darwin":
        for directory in ["/Applications/SuperCollider/", "/Applications/"]:
            if executable == "sclang":
                paths.append(directory + "SuperCollider.app/Contents/MacOS/")
            elif executable == "scsynth":
                paths.append(directory + "SuperCollider.app/Contents/Resources/")
    elif platform.system() == "Windows":
        paths.extend(glob.glob("C:/Program Files/SuperCollider-*/"))
    # elif platform.system() == "Linux":
    _LOGGER.debug("Searching executable in paths: %s", paths)
    extlist = [""]
    if os.name == "os2":
        _, ext = os.path.splitext(executable)
        # executable files on OS/2 can have an arbitrary extension, but
        # .exe is automatically appended if no dot is present in the name
        if not ext:
            executable += ".exe"
    elif platform.system() == "Windows":
        pathext = os.environ["PATHEXT"].lower().split(os.pathsep)
        _, ext = os.path.splitext(executable)
        if ext.lower() not in pathext:
            extlist = pathext

    for ext in extlist:
        execname = executable + ext
        for path in paths:
            file = os.path.join(path, execname)
            if os.path.isfile(file):
                return file
    raise FileNotFoundError(
        f"Unable to find '{executable}' executable in {paths} (platform.system={platform.system()})"
    )


def kill_processes(exec_path, allowed_parents: Optional[tuple] = None):
    """Kill processes with the same path for the executable.

    If allowed_parent is provided it will be searched in the names of the
    parent processes of the process with the executable path before terminating.
    If it is found the process won't be killed.

    Parameters
    ----------
    exec_path : str
        path of the executable to kill
    allowed_parent : str, optional
        parents name of processes to keep, by default None
    """
    _LOGGER.debug("Trying to find leftover processes of %s", exec_path)
    for proc in psutil.process_iter(["exe"]):
        if proc.info["exe"] == exec_path:
            parents = proc.parents()
            if allowed_parents and parents:
                parent_names = " ".join(map("".join, map(psutil.Process.name, parents)))
                _LOGGER.debug("Parents cmdlines: %s", parent_names)
                if any(
                    allowed_parent in parent_names for allowed_parent in allowed_parents
                ):
                    continue
            _LOGGER.warning(
                "Found old process. Please exit sc3nb via sc.exit(). \n"
                " Terminating %s because none of"
                " the parents=%s are in allowed_parents=%s"
                " More information can be found in the documentation.",
                proc,
                parents,
                allowed_parents,
            )
            proc.terminate()
            try:
                proc.wait(timeout=0.5)
            except psutil.TimeoutExpired:
                proc.kill()
                warnings.warn(f"Couldn't terminate {proc}")


class ProcessTimeout(Exception):
    """Process Timeout Exception"""

    def __init__(self, executable, output, timeout, expected):
        self.output = output
        self.timeout = timeout
        message = f"Reading of {executable} timed out after {timeout}s"
        if expected:
            message += f' while expecting: "{expected}"'
        super().__init__(message)


class Process:
    """Class for starting a executable and communication with it.

    Parameters
    ----------
    executable : str
        Name of executable to start
    programm_args : Optional[Sequence[str]], optional
        Arguments to program start with Popen, by default None
    executable_path : str, optional
        Path with executalbe, by default system PATH
    console_logging : bool, optional
        Flag for controlling console logging, by default True
    kill_others : bool, optional
        Flag for controlling killing of other executables with the same name.
        This is useful when processes where left over, by default True
    allowed_parents : Sequence[str], optional
        Sequence of parent names that won't be killed
        when kill_others is True, by default None
    """

    def __init__(
        self,
        executable: str,
        programm_args: Optional[Sequence[str]] = None,
        executable_path: str = None,
        console_logging: bool = True,
        kill_others: bool = True,
        allowed_parents: Sequence[str] = None,
    ):
        self.executable = executable
        self.exec_path = find_executable(self.executable, search_path=executable_path)
        self.console_logging = console_logging
        self.popen_args = [self.exec_path]
        if programm_args is not None:
            self.popen_args += programm_args

        # kill other (leftover) subprocesses
        # https://github.com/jupyter/jupyter_client/issues/104
        if kill_others:
            kill_processes(self.exec_path, allowed_parents)

        # starting subprocess
        _LOGGER.info("Popen args: %s", self.popen_args)
        self.popen = subprocess.Popen(
            args=self.popen_args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            universal_newlines=True,  # py3.8++ ==> text=True,
            errors="strict",
            bufsize=0,
        )
        # init queue for reading subprocess output queue
        self.output_queue = Queue()
        # output reading worker thread
        self.output_reader_thread = threading.Thread(
            target=self._read_loop, daemon=True
        )
        self.output_reader_thread.start()
        atexit.register(self.kill)

    def _read_loop(self):
        os.write(1, f"[{self.executable} | start reading ]\n".encode())
        for line in iter(self.popen.stdout.readline, ""):
            line = ANSI_ESCAPE.sub("", line)
            if self.console_logging:
                # print to jupyter console...
                os.write(1, f"[{self.executable}]  {line}".encode())
            self.output_queue.put(line)
        os.write(1, f"[{self.executable} | reached EOF ]\n".encode())
        return

    def read(self, expect: Optional[str] = None, timeout: float = 3) -> str:
        """Reads current output from output queue until expect is found

        Parameters
        ----------
        expect : str, optional
            str that we expect to find, by default None
        timeout : float, optional
            timeout in seconds for waiting for output, by default 3

        Returns
        -------
        str
            Output of process.

        Raises
        ------
        ProcessTimeout
            If neither output nor expect is found
        """
        timeout_time = time.time() + timeout
        out = ""
        expect_found = False
        while True:
            if time.time() >= timeout_time:
                raise ProcessTimeout(
                    executable=self.executable,
                    timeout=timeout,
                    output=out,
                    expected=expect,
                )
            try:
                new = self.output_queue.get_nowait()
                if new is not None:
                    out += new
                    if expect is not None and re.search(expect, out):
                        expect_found = True
            except Empty:
                if expect is None or expect_found:
                    return out.strip()
            time.sleep(0.001)

    def empty(self) -> None:
        """Empties output queue."""
        while True:
            try:
                self.output_queue.get_nowait()
            except Empty:
                return

    def write(self, input_str: str) -> None:
        """Send input to process

        Parameters
        ----------
        input_str : str
            Input to be send to process

        Raises
        ------
        RuntimeError
            If writing to process fails
        """
        _LOGGER.debug("Writing: '%s'", input_str)
        try:
            written = self.popen.stdin.write(input_str)
            self.popen.stdin.flush()  # shouldnt be needed as buffering is disabled.
            if written != len(input_str):
                raise RuntimeError(
                    f"Only written {written}/{len(input_str)} of input: '{input_str}'"
                )
        except OSError as error:
            raise RuntimeError("Write to stdin failed") from error

    def kill(self) -> int:
        """Kill the process.

        Returns
        -------
        int
            return code of process
        """
        if self.popen.poll() is None:
            self.popen.kill()
        self.output_reader_thread.join()
        return self.popen.wait()

    def __del__(self):
        self.kill()

    def __repr__(self) -> str:
        returncode = self.popen.returncode
        if returncode is None:
            process_status = f"pid={self.popen.pid}"
        else:
            process_status = f"returncode={returncode}"
        thread_status = "running" if self.output_reader_thread.is_alive() else "died"
        return f"<Process '{self.executable}' ({thread_status}) {process_status}>"
