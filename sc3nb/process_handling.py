""" Module for process handling. """

import logging
import os
import re
import subprocess
import sys
import threading
import time
import warnings
from queue import Empty, Queue
from typing import Optional

import psutil

_LOGGER = logging.getLogger(__name__)
_LOGGER.addHandler(logging.NullHandler())

ANSI_ESCAPE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
ALLOWED_PARENTS = ("scide", "python")


def find_executable(executable: str, path: str = None, add_to_path: bool = False):
    """Looks for executable in os $PATH or specified path

    Parameters
    ----------
    executable : str
        Executable to be found
    path : str, optional
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
    if path is not None:
        head, tail = os.path.split(path)
        if executable in tail:
            path = head
        if path not in os.environ["PATH"] and add_to_path:
            os.environ["PATH"] += os.pathsep + path

    if not path:
        path = os.environ["PATH"]
    paths = path.split(os.pathsep)
    extlist = [""]
    if os.name == "os2":
        _, ext = os.path.splitext(executable)
        # executable files on OS/2 can have an arbitrary extension, but
        # .exe is automatically appended if no dot is present in the name
        if not ext:
            executable = executable + ".exe"
    elif sys.platform == "win32":
        pathext = os.environ["PATHEXT"].lower().split(os.pathsep)
        _, ext = os.path.splitext(executable)
        if ext.lower() not in pathext:
            extlist = pathext
    for ext in extlist:
        execname = executable + ext
        if os.path.isfile(execname):
            return execname
        for path in paths:
            file = os.path.join(path, execname)
            if os.path.isfile(file):
                return file
    raise FileNotFoundError("Unable to find executable")


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
            if allowed_parents:
                parents = proc.parents()
                if parents:
                    parent_names = " ".join(
                        map("".join, map(psutil.Process.name, parents))
                    )
                    _LOGGER.debug("Parents cmdlines: %s", parent_names)
                    if any(
                        [
                            allowed_parent in parent_names
                            for allowed_parent in allowed_parents
                        ]
                    ):
                        continue
            _LOGGER.debug("Terminating %s parents: %s", proc, proc.parents())
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
    """Class for starting a executable and communication with it."""

    def __init__(
        self,
        executable,
        args=None,
        exec_path=None,
        console_logging=True,
        kill_others=True,
        allowed_parents=None,
    ):
        self.executable = executable
        self.exec_path = find_executable(self.executable, path=exec_path)
        self.console_logging = console_logging
        self.popen_args = [self.exec_path]
        if args is not None:
            self.popen_args += args

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
        self.stdin = self.popen.stdin
        # output reading worker thread
        self.output_reader_thread = threading.Thread(
            target=self._read_loop, daemon=True
        )
        self.output_reader_thread.start()

    def _read_loop(self):
        os.write(1, f"{self.executable} start reading\n".encode())
        for line in iter(self.popen.stdout.readline, ""):
            ANSI_ESCAPE.sub("", line)
            if self.console_logging:
                # print to jupyter console...
                os.write(1, f"{self.executable}:  {line}".encode())
            self.output_queue.put(line)
        os.write(1, f"{self.executable} reached EOF\n".encode())
        return

    def read(self, expect: Optional[str] = None, timeout: float = 1) -> str:
        """Reads current output from output queue or until expect is found

        Parameters
        ----------
        expect : str, optional
            str that we expect to find, by default None
        timeout : float, optional
            timeout for waiting for output, by default 1

        Returns
        -------
        str
            Output of process.

        Raises
        ------
        ProcessTimeout
            If no output or expectation isn't found
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
                if expect and not expect_found:
                    pass
                else:
                    return out
            time.sleep(0.001)

    def empty(self) -> None:
        """Empties output queue."""
        while True:
            try:
                self.output_queue.get_nowait()
            except Empty:
                return

    def send(self, input_str: str) -> None:
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
            self.stdin.write(input_str)
            self.stdin.flush()  # shouldnt be needed as buffering is disabled.
        except OSError as error:
            raise RuntimeError("Write to stdin failed") from error

    def kill(self) -> int:
        """Kill the process.

        Returns
        -------
        int
            return code of process
        """
        self.popen.kill()
        self.output_reader_thread.join()
        return self.popen.wait()

    def __del__(self):
        self.kill()
