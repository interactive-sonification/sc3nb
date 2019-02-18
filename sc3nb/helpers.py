"""Collection of small helper functions"""

import os
import re
import sys
import numbers

import pyaudio
import simpleaudio as sa
import numpy as np


def remove_comments(string):
    """Removes all //single-line or /* multi-line */ c-style comments

    Arguments:
        string {str} -- Code

    Returns:
        str -- Code without comments
    """

    # function code by Onur Yildirim
    # first group captures quoted strings (double or single)
    # second group captures comments (//single-line or /* multi-line */)
    # alternative cares for escaped quotes
    # pattern = r"(\".*?(?<!\\)\"|\'.*?(?<!\\)\')|(/\*.*?\*/|//[^\r\n]*$)"
    pattern = r"(\".*?\"|\'.*?\')|(/\*.*?\*/|//[^\r\n]*$)"
    regex = re.compile(pattern, re.MULTILINE | re.DOTALL)

    def _replacer(match):
        # if the 2nd group (capturing comments) is not None,
        # it means we have captured a non-quoted (real) comment string.
        if match.group(2) is not None:
            return ""  # so we will return empty to remove the comment
        else:  # otherwise, we will return the 1st group
            return match.group(1)  # captured quoted-string
    return regex.sub(_replacer, string)

def find_executable(executable, path=''):
    """Looks for executable in os $PATH or specified path

    Arguments:
        executable {str} -- Executable to be found

    Keyword Arguments:
        path {str} -- Path at which to look for
                      executable (default: {''})

    Raises:
        FileNotFoundError -- Raised if executable
                             cannot be found

    Returns:
        str -- Full path to executable
    """

    if not path:
        path = os.environ['PATH']
    paths = path.split(os.pathsep)
    extlist = ['']
    if os.name == 'os2':
        _, ext = os.path.splitext(executable)
        # executable files on OS/2 can have an arbitrary extension, but
        # .exe is automatically appended if no dot is present in the name
        if not ext:
            executable = executable + ".exe"
    elif sys.platform == 'win32':
        pathext = os.environ['PATHEXT'].lower().split(os.pathsep)
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
    raise FileNotFoundError("Unable to find sclang executable")


def linlin(x, smi, sma, dmi, dma):
    """TODO

    Arguments:
        x {float} -- [description]
        smi {float} -- [description]
        sma {float} -- [description]
        dmi {float} -- [description]
        dma {float} -- [description]

    Returns:
        float -- [description]
    """

    return (x-smi)/(sma-smi)*(dma-dmi) + dmi


def midicps(m):
    """TODO

    Arguments:
        m {int} -- [description]

    Returns:
        float -- [description]
    """

    return 440.0*2**((m-69)/12.0)


def cpsmidi(c):
    """TODO

    Arguments:
        c {float} -- [description]

    Returns:
        float -- [description]
    """

    return 69+12*np.log2(c/440.0)


def clip(value, minimum=-float("inf"), maximum=float("inf")):
    """Clips a value to a certain range

    Arguments:
        value {float} -- Value to clip

    Keyword Arguments:
        minimum {float} -- Minimum value output can take
                           (default: {-float("inf")})
        maximum {float} -- Maximum value output can take
                            (default: {float("inf")})

    Returns:
        float -- clipped value
    """

    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def dbamp(db):
    """TODO

    Arguments:
        db {[type]} -- [description]

    Returns:
        [type] -- [description]
    """

    return 10**(db/20.0)


def ampdb(amp):
    """TODO

    Arguments:
        amp {[type]} -- [description]

    Returns:
        [type] -- [description]
    """

    return 20*np.log10(amp)

# service functions to play and record data arrays from within python


def play(sig, num_channels=1, sr=44100, norm=True, block=False):
    """Plays audio signal

    Arguments:
        sig {iterable} -- Signal to be played

    Keyword Arguments:
        num_channels {int} -- Number of channels (default: {1})
        sr {int} -- Audio sample rate (default: {44100})
        norm {bool} -- if True, normalize signal
                       (default: {True})
        block {bool} -- if True, block until playback is finished
                        (default: {False})

    Returns:
        [type] -- [description]
    """

    factor = 1
    if isinstance(norm, bool) and norm:
        factor = 1 / np.max(np.abs(sig))
    elif isinstance(norm, numbers.Number):
        factor = norm
    asig = (32767 * factor * sig).astype(np.int16)
    play_obj = sa.play_buffer(asig, num_channels, 2, sr)
    if block:
        play_obj.wait_done() # wait for playback to finish before returning
    return play_obj


def record(dur=2, channels=1, rate=44100, chunk=256):
    """Record audio

    Keyword Arguments:
        dur {int} -- Duration (default: {2})
        channels {int} -- Number of channels (default: {1})
        rate {int} -- Audio sample rate (default: {44100})
        chunk {int} -- Chunk size (default: {256})

    Returns:
        ndarray -- Recorded signal
    """

    p = pyaudio.PyAudio()
    stream = p.open(format=pyaudio.paInt16, channels=channels, rate=rate, input=True,
                    output=True, frames_per_buffer=chunk)
    buflist = []
    for _ in range(0, int(rate/chunk*dur)):
        data = stream.read(chunk)
        buflist.append(data)
    stream.stop_stream()
    stream.close()
    p.terminate()
    return np.frombuffer(b''.join(buflist), dtype=np.int16)
