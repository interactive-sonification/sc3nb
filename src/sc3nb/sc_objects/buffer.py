"""Module for using SuperCollider Buffers in Python"""

import os
import warnings
from enum import Enum, unique
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import TYPE_CHECKING, Any, List, NamedTuple, Optional, Sequence, Union

import numpy as np
import scipy.io.wavfile as wavfile

import sc3nb
from sc3nb.sc_objects.node import Synth
from sc3nb.sc_objects.synthdef import SynthDef

if TYPE_CHECKING:
    import pya

    from sc3nb.sc_objects.server import SCServer


@unique
class BufferReply(str, Enum):
    """Buffer Command Replies"""

    INFO = "/b_info"


@unique
class BufferCommand(str, Enum):
    """Buffer OSC Commands for Buffers"""

    ALLOC = "/b_alloc"
    ALLOC_READ = "/b_allocRead"
    ALLOC_READ_CHANNEL = "/b_allocReadChannel"
    READ = "/b_read"
    READ_CHANNEL = "/b_readChannel"
    WRITE = "/b_write"
    FREE = "/b_free"
    ZERO = "/b_zero"
    SET = "/b_set"
    SETN = "/b_setn"
    FILL = "/b_fill"
    GEN = "/b_gen"
    CLOSE = "/b_close"
    QUERY = "/b_query"
    GET = "/b_get"
    GETN = "/b_getn"


@unique
class BufferAllocationMode(str, Enum):
    """Buffer Allocation Modes"""

    FILE = "file"
    ALLOC = "alloc"
    DATA = "data"
    EXISTING = "existing"
    COPY = "copy"
    NONE = "none"


class BufferInfo(NamedTuple):
    """Information about the Buffer"""

    bufnum: int
    num_frames: int
    num_channels: int
    sample_rate: float


class Buffer:
    """A Buffer object represents a SuperCollider3 Buffer on scsynth
    and provides access to low-level buffer commands of scsynth via
    methods of the Buffer objects.

    The constructor merely initializes a buffer:

    * it selects a buffer number using the server's buffer allocator
    * it initializes attribute variables

    Parameters
    ----------
    bufnum : int, optional
        buffer number to be used on scsynth. Defaults to None,
        can be set to enforce a given bufnum
    server : SCServer, optional
        The server instance to establish the Buffer,
        by default use the SC default server

    Attributes
    ----------
    server : the SCServer object
        to communicate with scsynth
    _bufnum : int
        buffer number = bufnum id on scsynth
    _sr : int
        the sampling rate of the buffer
    _channels : int
        number of channels of the buffer
    _samples : int
        buffer length = number of sample frames
    _alloc_mode : str
        ['file', 'alloc', 'data', 'existing', 'copy']
        according to previously used generator, defaults to None
    _allocated : boolean
        True if Buffer has been allocated by
        any of the initialization methods
    _path : str
        path to the audio file used in load_file()

    Notes
    -----
    For more information on Buffer commands, refer to the Server Command Reference in SC3.
    https://doc.sccode.org/Reference/Server-Command-Reference.html#Buffer%20Commands

    Examples
    --------
    (see examples/buffer-examples.ipynb)

    >>> b = Buffer().load_file(...)
    >>> b = Buffer().load_data(...)
    >>> b = Buffer().alloc(...)
    >>> b = Buffer().load_asig(...)
    >>> b = Buffer().use_existing(...)
    >>> b = Buffer().copy(Buffer)

    """

    def __init__(
        self, bufnum: Optional[int] = None, server: Optional["SCServer"] = None
    ) -> None:
        self._server = server or sc3nb.SC.get_default().server
        self._bufnum_set_manually = bufnum is not None
        self._bufnum = bufnum
        self._sr = None
        self._channels = None
        self._samples = None
        self._alloc_mode = BufferAllocationMode.NONE
        self._allocated = False
        self._path = None
        self._synth_def = None
        self._synth = None

    # Section: Buffer initialization methods
    def read(
        self,
        path: str,
        starting_frame: int = 0,
        num_frames: int = -1,
        channels: Optional[Union[int, Sequence[int]]] = None,
    ) -> "Buffer":
        """Allocate buffer memory and read a sound file.

        If the number of frames argument num_frames is negative or zero,
        the entire file is read.

        Parameters
        ----------
        path : string
            path name of a sound file.
        starting_frame : int
            starting frame in file
        num_frames : int
            number of frames to read
        channels : list | int
            channels and order of channels to be read from file.
            if only a int is provided it is loaded as only channel

        Returns
        -------
        self : Buffer
            the created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is already allocated.
        """
        if self._allocated:
            raise RuntimeError("Buffer object is already initialized!")
        if self._bufnum is None:
            self._bufnum = self._server.buffer_ids.allocate(num=1)[0]
        self._alloc_mode = BufferAllocationMode.FILE
        self._path = Path(path).resolve(strict=True)
        self._sr, data = wavfile.read(
            self._path
        )  # TODO: we only need the metadata here
        server_sr = self._server.nominal_sr
        if self._sr != server_sr:
            warnings.warn(
                f"Sample rate of file ({self._sr}) does not "
                f"match the SC Server sample rate ({server_sr})"
            )
        self._samples = data.shape[0] if num_frames <= 0 else num_frames
        if channels is None:
            channels = [0] if len(data.shape) == 1 else range(data.shape[1])
        elif isinstance(channels, int):
            channels = [channels]
        self._channels = len(channels)
        self._server.msg(
            BufferCommand.ALLOC_READ_CHANNEL,
            [self._bufnum, str(self._path), starting_frame, num_frames, *channels],
            bundle=True,
        )
        self._allocated = True
        return self

    def alloc(self, size: int, sr: int = 44100, channels: int = 1) -> "Buffer":
        """Allocate buffer memory.

        Parameters
        ----------
        size : int
            number of frames
        sr : int
            sampling rate in Hz (optional. default = 44100)
        channels : int
            number of channels (optional. default = 1 channel)

        Returns
        -------
        self : Buffer
            the created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is already allocated.
        """
        if self._allocated:
            raise RuntimeError("Buffer object is already initialized!")
        if self._bufnum is None:
            self._bufnum = self._server.buffer_ids.allocate(num=1)[0]
        self._sr = sr
        self._alloc_mode = BufferAllocationMode.ALLOC
        self._channels = channels
        self._samples = int(size)
        self._server.msg(
            BufferCommand.ALLOC, [self._bufnum, size, channels], bundle=True
        )
        self._allocated = True
        return self

    def load_data(
        self,
        data: np.ndarray,
        sr: int = 44100,
        mode: str = "file",
        sync: bool = True,
    ) -> "Buffer":
        """Allocate buffer memory and read input data.

        Parameters
        ----------
        data : numpy array
            Data which should inserted
        sr : int, default: 44100
            sample rate
        mode : 'file' or 'osc'
            Insert data via filemode ('file') or n_set OSC commands ('osc')
            Bundling is only supported for 'osc' mode and if sync is False.
        sync: bool, default: True
            Use SCServer.sync after sending messages when mode = 'osc'

        Returns
        -------
        self : Buffer
            the created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is already allocated.
        """
        if self._allocated:
            raise RuntimeError("Buffer object is already initialized!")
        if self._bufnum is None:
            self._bufnum = self._server.buffer_ids.allocate(num=1)[0]
        self._alloc_mode = BufferAllocationMode.DATA
        self._sr = sr
        self._samples = data.shape[0]
        self._channels = 1 if len(data.shape) == 1 else data.shape[1]
        if mode == "file":
            tempfile = NamedTemporaryFile(delete=False)
            try:
                wavfile.write(tempfile, self._sr, data)
            finally:
                tempfile.close()
            self._server.msg(
                BufferCommand.ALLOC_READ,
                [self._bufnum, tempfile.name],
                await_reply=True,
            )
            if os.path.exists(tempfile.name):
                os.remove(tempfile.name)
        elif mode == "osc":
            self._server.msg(
                BufferCommand.ALLOC, [self._bufnum, data.shape[0]], bundle=True
            )
            blocksize = 1000  # array size compatible with OSC packet size
            # TODO: check how this depends on datagram size
            # TODO: put into Buffer header as const if needed elsewhere...
            if self._channels > 1:
                data = data.reshape(-1, 1)
            if data.shape[0] < blocksize:
                self._server.msg(
                    BufferCommand.SETN,
                    [self._bufnum, [0, data.shape[0], data.tolist()]],
                    bundle=True,
                )
            else:
                # For datasets larger than {blocksize} entries,
                # split data to avoid network problems
                splitdata = np.array_split(data, data.shape[0] / blocksize)
                for i, chunk in enumerate(splitdata):
                    self._server.msg(
                        BufferCommand.SETN,
                        [self._bufnum, i * blocksize, chunk.shape[0], chunk.tolist()],
                        await_reply=False,
                        bundle=True,
                    )
                if sync:
                    self._server.sync()
        else:
            raise ValueError(f"Unsupported mode '{mode}'.")
        self._allocated = True
        return self

    def load_collection(
        self, data: np.ndarray, mode: str = "file", sr: int = 44100
    ) -> "Buffer":
        """Wrapper method of :func:`Buffer.load_data`"""
        return self.load_data(data, sr=sr, mode=mode)

    def load_asig(self, asig: "pya.Asig", mode: str = "file") -> "Buffer":
        """Create buffer from asig

        Parameters
        ----------
        asig : pya.Asig
            asig to be loaded in buffer
        mode : str, optional
            Insert data via filemode ('file') or n_set OSC commands ('osc'), by default 'file'

        Returns
        -------
        self : Buffer
            the created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is already allocated.
        """
        if self._allocated:
            raise RuntimeError("Buffer object is already initialized!")
        return self.load_data(asig.sig, sr=asig.sr, mode=mode)

    def use_existing(self, bufnum: int, sr: int = 44100) -> "Buffer":
        """Creates a buffer object from already existing Buffer bufnum.

        Parameters
        ----------
        bufnum : int
            buffer node id
        sr : int
            Sample rate

        Returns
        -------
        self : Buffer
            the created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is already allocated.
        """
        if self._allocated:
            raise RuntimeError("Buffer object is already initialized!")

        self._alloc_mode = BufferAllocationMode.EXISTING
        self._sr = sr
        self._bufnum = bufnum
        self._allocated = True
        info = self.query()
        self._samples = info.num_frames
        self._channels = info.num_channels
        return self

    def copy_existing(self, buffer: "Buffer") -> "Buffer":
        """Duplicate an existing buffer

        Parameters
        ----------
        buffer : Buffer object
            Buffer which should be duplicated

        Returns
        -------
        self : Buffer
            the newly created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is already allocated.
        """
        if self._allocated:
            raise RuntimeError("Buffer object is already initialized!")
        if not buffer.allocated:
            raise RuntimeError("Other Buffer object is not initialized!")

        # If both buffers use the same server -> copy buffer directly in the server
        if self._server is buffer._server:
            self.alloc(buffer.samples, buffer.sr, buffer.channels)
            self.gen_copy(buffer, 0, 0, -1)
        else:
            # both sc instances must have the same file server
            self._sr = buffer.sr
            tempfile = NamedTemporaryFile(delete=False)
            tempfile.close()
            try:
                buffer.write(tempfile.name)
                self.read(tempfile.name)
            finally:
                if os.path.exists(tempfile.name):
                    os.remove(tempfile.name)
        self._alloc_mode = BufferAllocationMode.COPY
        return self

    # Section: Buffer modification methods
    def fill(self, start: int = 0, count: int = 0, value: float = 0) -> "Buffer":
        """Fill range of samples with value(s).

        Parameters
        ----------
        start : int or list
            int : sample starting index
            list : n*[start, count, value] list
        count : int
            number of samples to fill
        value : float
            value

        Returns
        -------
        self : Buffer
            the created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        # TODO implement this correctly
        if not self._allocated:
            raise RuntimeError("Buffer object is not initialized!")

        values = [start, count, value] if not isinstance(start, list) else start
        self._server.msg(BufferCommand.FILL, [self._bufnum] + values, bundle=True)
        return self

    def gen(self, command: str, args: List[Any]) -> "Buffer":
        """Call a command to fill a buffer.
        If you know, what you do -> you can use this method.

        See Also
        --------
        gen_sine1, gen_sine2, gen_cheby, gen_cheby, gen_copy

        Parameters
        ----------
        command : str
            What fill command to use.
        args : List[Any]
            Arguments for command

        Returns
        -------
        self : Buffer
            the created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        if not self._allocated:
            raise RuntimeError("Buffer object is not initialized!")
        self._server.msg(BufferCommand.GEN, [self._bufnum, command] + args, bundle=True)
        return self

    def zero(self) -> "Buffer":
        """Set buffer data to zero.

        Returns
        -------
        self : Buffer
            the created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        if not self._allocated:
            raise RuntimeError("Buffer object is not initialized!")
        self._server.msg(BufferCommand.ZERO, [self._bufnum], bundle=True)
        return self

    def gen_sine1(
        self,
        amplitudes: List[float],
        normalize: bool = False,
        wavetable: bool = False,
        clear: bool = False,
    ) -> "Buffer":
        """Fill the buffer with sine waves & given amplitude

        Parameters
        ----------
        amplitudes : list
            The first float value specifies the amplitude of the first partial,
            the second float value specifies the amplitude of the second
            partial, and so on.
        normalize : bool
            Normalize peak amplitude of wave to 1.0.
        wavetable : bool
            If set, then the buffer is written in wavetable format so that it
            can be read by interpolating oscillators.
        clear : bool
            If set then the buffer is cleared before new partials are written
            into it. Otherwise the new partials are summed with the existing
            contents of the buffer

        Returns
        -------
        self : Buffer
            the created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        return self.gen(
            "sine1", [self._gen_flags(normalize, wavetable, clear), amplitudes]
        )

    def gen_sine2(
        self,
        freq_amps: List[float],
        normalize: bool = False,
        wavetable: bool = False,
        clear: bool = False,
    ) -> "Buffer":
        """Fill the buffer with sine waves
        given list of [frequency, amplitude] lists

        Parameters
        ----------
        freq_amps : list
            Similar to sine1 except that each partial frequency is specified
            explicitly instead of being an integer multiple of the fundamental.
            Non-integer partial frequencies are possible.
        normalize : bool
            If set, normalize peak amplitude of wave to 1.0.
        wavetable : bool
            If set, the buffer is written in wavetable format so that it
            can be read by interpolating oscillators.
        clear : bool
            If set, the buffer is cleared before new partials are written
            into it. Otherwise the new partials are summed with the existing
            contents of the buffer.

        Returns
        -------
        self : Buffer
            the created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        return self.gen(
            "sine2", [self._gen_flags(normalize, wavetable, clear), freq_amps]
        )

    def gen_sine3(
        self,
        freqs_amps_phases: List[float],
        normalize: bool = False,
        wavetable: bool = False,
        clear: bool = False,
    ) -> "Buffer":
        """Fill the buffer with sine waves & given a list of
        [frequency, amplitude, phase] entries.

        Parameters
        ----------
        freqs_amps_phases : list
            Similar to sine2 except that each partial may have a
            nonzero starting phase.
        normalize : bool
            if set, normalize peak amplitude of wave to 1.0.
        wavetable : bool
            If set, the buffer is written in wavetable format
            so that it can be read by interpolating oscillators.
        clear : bool
            If set, the buffer is cleared before new partials are written
            into it. Otherwise the new partials are summed with the existing
            contents of the buffer.

        Returns
        -------
        self : Buffer
            the created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        return self.gen(
            "sine3", [self._gen_flags(normalize, wavetable, clear), freqs_amps_phases]
        )

    def gen_cheby(
        self,
        amplitudes: List[float],
        normalize: bool = False,
        wavetable: bool = False,
        clear: bool = False,
    ) -> "Buffer":
        """Fills a buffer with a series of chebyshev polynomials, which can be
        defined as cheby(n) = amplitude * cos(n * acos(x))

        Parameters
        ----------
        amplitudes : list
            The first float value specifies the amplitude for n = 1,
            the second float value specifies the amplitude
            for n = 2, and so on
        normalize : bool
            If set, normalize the peak amplitude of the Buffer to 1.0.
        wavetable : bool
            If set, the buffer is written in wavetable format so that it
            can be read by interpolating oscillators.
        clear : bool
            If set the buffer is cleared before new partials are written
            into it. Otherwise the new partials are summed with the existing
            contents of the buffer.

        Returns
        -------
        self : Buffer
            the created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        return self.gen(
            "cheby", [self._gen_flags(normalize, wavetable, clear), amplitudes]
        )

    def gen_copy(
        self, source: "Buffer", source_pos: int, dest_pos: int, copy_amount: int
    ) -> "Buffer":
        """Copy samples from the source buffer to the destination buffer
        specified in the b_gen command.

        Parameters
        ----------
        source : Buffer
            Source buffer object
        source_pos : int
            sample position in source
        dest_pos : int
            sample position in destination
        copy_amount : int
            number of samples to copy. If the number of samples to copy is
            negative, the maximum number of samples
            possible is copied.

        Returns
        -------
        self : Buffer
            the created Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        return self.gen("copy", [dest_pos, source.bufnum, source_pos, copy_amount])

    # Section: Buffer output methods
    def play(
        self, rate: float = 1, loop: bool = False, pan: float = 0, amp: float = 0.3
    ) -> Synth:
        """Play the Buffer using a Synth

        Parameters
        ----------
        rate : float, optional
            plackback rate, by default 1
        loop : bool, optional
            if True loop the playback, by default False
        pan : int, optional
            pan position, -1 is left, +1 is right, by default 0
        amp : float, optional
            amplitude, by default 0.3

        Returns
        -------
        Synth
            Synth to control playback.

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        if not self._allocated:
            raise RuntimeError("Buffer object is not initialized!")

        if self._synth_def is None:
            playbuf_def = """
            { |out=0, bufnum=^bufnum, rate=^rate, loop=^loop, pan=^pan, amp=^amp |
                    var sig = PlayBuf.ar(^num_channels, bufnum,
                        rate*BufRateScale.kr(bufnum),
                        loop: loop,
                        doneAction: Done.freeSelf);
                    Out.ar(out, Pan2.ar(sig, pan, amp))
            }"""
            self._synth_def = SynthDef(
                name=f"sc3nb_playbuf_{self.bufnum}", definition=playbuf_def
            )
            synth_name = self._synth_def.add(
                pyvars={
                    "num_channels": self.channels,
                    "bufnum": self.bufnum,
                    "rate": rate,
                    "loop": 1 if loop else 0,
                    "pan": pan,
                    "amp": amp,
                }
            )
            self._synth = Synth(name=synth_name, server=self._server)
        else:
            self._synth.new(
                {"rate": rate, "loop": 1 if loop else 0, "pan": pan, "amp": amp}
            )
        return self._synth

    def write(
        self,
        path: str,
        header: str = "wav",
        sample: str = "float",
        num_frames: int = -1,
        starting_frame: int = 0,
        leave_open: bool = False,
    ) -> "Buffer":
        """Write buffer data to a sound file

        Parameters
        ----------
        path : string
            path name of a sound file.
        header : string
            header format. Header format is one of:
            "aiff", "next", "wav", "ircam"", "raw"
        sample : string
            sample format. Sample format is one of:
            "int8", "int16", "int24", "int32",
            "float", "double", "mulaw", "alaw"
        num_frames : int
            number of frames to write.
            -1 means all frames.
        starting_frame : int
            starting frame in buffer
        leave_open : boolean
            Whether you want the buffer file left open.
            For use with DiskOut you will want this to be true.
            The file is created, but no frames are written until the DiskOut UGen does so.
            The default is false which is the correct value for all other cases.

        Returns
        -------
        self : Buffer
            the Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        if not self._allocated:
            raise RuntimeError("Buffer object is not initialized!")
        leave_open_val = 1 if leave_open else 0
        path = str(Path(path).resolve())
        self._server.msg(
            BufferCommand.WRITE,
            [
                self._bufnum,
                path,
                header,
                sample,
                num_frames,
                starting_frame,
                leave_open_val,
            ],
            bundle=True,
        )
        return self

    def close(self) -> "Buffer":
        """Close soundfile after using a Buffer with DiskOut

        Returns
        -------
        self : Buffer
            the Buffer object

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        if not self._allocated:
            raise RuntimeError("Buffer object is not initialized!")
        self._server.msg(BufferCommand.CLOSE, [self._bufnum], bundle=True)
        return self

    def to_array(self) -> np.ndarray:
        """Return the buffer data as an array representation.

        Returns
        -------
        np.ndarray:
            Values of the buffer

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        if not self._allocated:
            raise RuntimeError("Buffer object is not initialized!")
        data = []
        blocksize = 1000  # array size compatible with OSC packet size
        i = 0
        num_samples = self._samples * self._channels
        while i < num_samples:
            bs = blocksize if i + blocksize < num_samples else num_samples - i
            tmp = self._server.msg(
                BufferCommand.GETN, [self._bufnum, i, bs], bundle=False
            )
            data += list(tmp)[3:]  # skip first 3 els [bufnum, startidx, size]
            i += bs
        data = np.array(data).reshape((-1, self._channels))
        return data

    # Section: Buffer information methods
    def query(self) -> BufferInfo:
        """Get buffer info.

        Returns
        -------
        Tuple:
            (buffer number, number of frames, number of channels, sampling rate)

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        if not self._allocated:
            raise RuntimeError("Buffer object is not initialized!")
        return BufferInfo._make(
            self._server.msg(BufferCommand.QUERY, [self._bufnum], bundle=False)
        )

    def __repr__(self) -> str:
        if self.samples is None or self.sr is None:
            duration = 0
        else:
            duration = self.samples / self.sr
        return (
            f"<Buffer({self.bufnum}) on {self._server.addr}:"
            + f" {self.channels} x {self.samples} @ {self.sr} Hz = {duration:.3f}s"
            + f""" {["not loaded", "allocated"][self.allocated]}"""
            + f" using mode '{self._alloc_mode}'>"
        )

    # Section: Methods to delete / free Buffers
    def free(self) -> None:
        """Free buffer data.

        Raises
        ------
        RuntimeError
            If the Buffer is not allocated yet.
        """
        if not self._allocated:
            raise RuntimeError("Buffer object is not initialized!")
        if (
            self._alloc_mode != BufferAllocationMode.EXISTING
            and not self._bufnum_set_manually
        ):
            self._server.buffer_ids.free([self._bufnum])
        self._server.msg(BufferCommand.FREE, [self._bufnum], bundle=True)
        self._allocated = False
        self._alloc_mode = BufferAllocationMode.NONE

    # Section: Properties
    @property
    def bufnum(self) -> Optional[int]:
        """Buffer number which serves as ID in SuperCollider

        Returns
        -------
        int
            bufnum
        """
        return self._bufnum

    @property
    def allocated(self) -> bool:
        """Whether this Buffer is allocated by
        any of the initialization methods.

        Returns
        -------
        bool
            True if allocated
        """
        return self._allocated

    @property
    def alloc_mode(self) -> BufferAllocationMode:
        """Mode of Buffer allocation.

        One of ['file', 'alloc', 'data', 'existing', 'copy']
        according to previously used generator.
        Defaults to None if not allocated.

        Returns
        -------
        str
            allocation mode
        """
        return self._alloc_mode

    @property
    def path(self) -> Optional[Path]:
        """File path that was provided to read.

        Returns
        -------
        pathlib.Path
            buffer file path
        """
        return self._path

    @property
    def channels(self) -> Optional[int]:
        """Number of channels in the Buffer.

        Returns
        -------
        int
            channel number
        """
        return self._channels

    @property
    def samples(self) -> Optional[int]:
        """Number of samples in the buffer.

        Returns
        -------
        int
            sample number
        """
        return self._samples

    @property
    def sr(self) -> Optional[int]:
        """Sampling rate of the Buffer.

        Returns
        -------
        int
            sampling rate
        """
        return self._sr

    @property
    def duration(self) -> Optional[float]:
        """Duration of the Buffer in seconds.

        Returns
        -------
        float
            duration in seconds
        """
        if self._samples is not None and self._sr is not None:
            return self._samples / self._sr
        else:
            return None

    @property
    def server(self) -> "SCServer":
        """The server where this Buffer is placed.

        Returns
        -------
        SCServer
            The server where this Buffer is placed.
        """
        return self._server

    # Section: Private utils
    def _gen_flags(self, a_normalize=False, a_wavetable=False, a_clear=False) -> int:
        """Generate Wave Fill Commands flags from booleans
        according to the SuperCollider Server Command Reference.

        Parameters
        ----------
        a_normalize : bool, optional
            Normalize peak amplitude of wave to 1.0, by default False
        a_wavetable : bool, optional
            If set, then the buffer is written in wavetable
            format so that it can be read by interpolating
            oscillators, by default False
        a_clear : bool, optional
            If set then the buffer is cleared before new partials are written
            into it. Otherwise the new partials are summed with the existing
            contents of the buffer, by default False

        Returns
        -------
        int
            Wave Fill Commands flags
        """
        normalize = 1 if a_normalize is True else 0
        wavetable = 2 if a_wavetable is True else 0
        clear = 4 if a_clear is True else 0
        return normalize + wavetable + clear
