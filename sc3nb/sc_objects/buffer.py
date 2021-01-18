"""Module to for using SuperCollider Buffers in Python"""

import os

import scipy.io.wavfile as wavfile
import numpy as np

import sc3nb

# Buffer altering
# /b_read           Read sound file data into an existing buffer.
# /b_readChannel    Read sound file channel data into an existing buffer.
# /b_set


class Buffer:
    """A Buffer object represents a SuperCollider3 Buffer on scsynth
    and provides access to low-level buffer commands of scsynth via
    methods of the Buffer objects.

    The constructor merely initializes a buffer:
    * it selects a buffer number using SC's buffer allocator
    * it initializes attribute variables

    For more information on Buffer commands in sc3, refer to the Server Command
    Reference in sc3 help.

    Parameters
    ----------
    sc : object of type SC
        The server instance to establish the Buffer
    bufnum : int
        buffer number to be used on scsynth. Defaults to None
        can be set to enforce a given bufnum

    Attributes
    ----------
    sc : the SC object
        to communicate with scsynth
    _sr : int
        the sampling rate of the buffer
    _channels: int
        number of channels of the buffer
    _samples: int
        buffer length = number of sample frames
    _bufnum : int
        buffer number = bufnum id on scsynth
    _alloc_mode : str
        ['file', 'alloc', 'data', 'existing', 'copy']
        according to previously used generator, defaults to None
    _path : string
        path to the audio file used in load_file()
    _tempfile : string
        filename (if created) of temporary file
        used for data transfer to scsynth
    _allocated : boolean
        True if Buffer has been allocated by
        any of the initialization methods

    See Also
    --------
    --

    Notes
    -----
    The default way of allocating a Buffer would be
        b1 = scn.Buffer(sc).alloc(44100)
    For convenience, a method named Buffer() (sic: capital 'B')
    has been added to class SC which forwards self to calling the
    Buffer constructor, allowing instead to write
        b1 = sc.Buffer().alloc(44100)

    Examples
    --------
    (see examples/buffer-examples.ipynb)
    b = Buffer().load_file(...)
    b = Buffer().load_data(...)
    b = Buffer().alloc(...)
    b = Buffer().load_asig(...)
    b = Buffer().use_existing(...)
    b = Buffer().copy(Buffer)

    Returns
    -------
    self : Buffer
        the created Buffer object

    """

    def __init__(self, bufnum=None, server=None):
        self.server = server or sc3nb.SC.default.server
        if bufnum is None:
            self._bufnum = self.server.next_buffer_id()
        else:  # force given bufnum
            self._bufnum = bufnum
        self._sr = None
        self._channels = None
        self._samples = None
        self._alloc_mode = None
        self._allocated = False
        self._tempfile = None
        self._path = None
        self._synth_def = None
        self._synth = None

    # Section: Buffer initialization methods
    def read(self, path, starting_frame=0, num_frames=-1, channels=None):
        """Allocate buffer space and read a sound file.

        If the number of frames argument is less than or equal to zero,
        the entire file is read.

        Parameters
        ----------
        path: string
            path name of a sound file.
        starting_frame: int
            starting frame in file
        num_frames: int
            number of frames to read
        channels: list | int
            channels and order of channels to be read from file.
            if only a int is provided it is loaded as only channel

        Returns
        -------
        self : Buffer
            the created Buffer object
        """
        self._alloc_mode = 'file'
        self._sr, data = wavfile.read(path)  # TODO: we only need the metadata here
        if num_frames <= 0:
            self._samples = data.shape[0]
        else:
            self._samples = num_frames
        if channels is None:
            if len(data.shape) == 1:
                channels = [0]
            else:
                channels = range(data.shape[1])
        elif isinstance(channels, int):
            channels = [channels]
        self._channels = len(channels)
        self._path = path
        self.server.msg(
            "/b_allocReadChannel",
            [self._bufnum, path, starting_frame, num_frames, *channels])
        self._allocated = True
        return self

    def alloc(self, size, sr=44100, channels=1):
        """Allocate buffer space.

        Parameters
        ----------
        size: int
            number of frames
        sr: int
            sampling rate in Hz (optional. default = 44100)
        channels: int
            number of channels (optional. default = 1 channel)

        Returns
        -------
        self : Buffer
            the created Buffer object
        """
        self._sr = sr
        self._alloc_mode = 'alloc'
        self._channels = channels
        self._samples = int(size)
        self.server.msg("/b_alloc", [self._bufnum, size, channels])
        self._allocated = True
        return self

    def load_data(self, data, mode='file', sr=44100):
        """Allocate buffer space and read input data.

        Parameters
        ----------
        data: numpy array
            Data which should inserted
        mode: string='file'
            Insert data via filemode ('file') or n_set OSC commands ('osc')
        sr: int=44100
            sample rate

        Returns
        -------
        self : Buffer
            the created Buffer object
        """
        self._alloc_mode = 'data'
        self._sr = sr
        self._samples = data.shape[0]
        self._channels = 1 if len(data.shape) == 1 else data.shape[1]
        if mode == 'file':
            if not os.path.exists('./temp/'):
                os.makedirs('./temp/')
            self._tempfile = f"./temp/temp_{self._bufnum}.wav"
            wavfile.write(self._tempfile, self._sr, data)
            self.server.msg("/b_allocRead", [self._bufnum, self._tempfile])
        elif mode == 'osc':
            self.server.msg("/b_alloc", [self._bufnum, data.shape[0]])
            blocksize = 1000  # array size compatible with OSC packet size
            # TODO: check how this depends on datagram size
            # TODO: put into Buffer header as const if needed elsewhere...
            if self._channels > 1:
                data = data.reshape(-1, 1)
            if data.shape[0] < blocksize:
                self.server.msg("/b_setn",
                            [self._bufnum, [0, data.shape[0], data.tolist()]],)
            else:
                # For datasets larger than {blocksize} entries,
                # split data to avoid network problems
                splitdata = np.array_split(data, data.shape[0]/blocksize)
                for i, chunk in enumerate(splitdata):
                    self.server.msg("/b_setn",
                                [self._bufnum, i * blocksize, chunk.shape[0], chunk.tolist()],
                                 sync=False)
                self.server.sync()
        else:
            raise ValueError(f"Unsupported mode '{mode}'.")
        self._allocated = True
        return self

    def load_collection(self, data, mode='file', sr=44100):
        """Wrapper method of :func:`Buffer.load_data`"""
        return self.load_data(data, mode, sr)

    def load_asig(self, asig, mode='file'):
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
        """
        # ToDo: issue warning is not isinstance(asig, pya.Asig)
        return self.load_data(asig.sig, mode, sr=asig.sr)

    def use_existing(self, bufnum, sr=44100):
        """Creates a buffer object from already existing Buffer bufnum.

        Parameters
        ----------
        bufnum: int
            buffer node id
        sr: int
            Sample rate

        Returns
        -------
        self : Buffer
            the created Buffer object
        """
        self._alloc_mode = 'existing'
        self._sr = sr
        self._bufnum = bufnum
        self._allocated = True
        info = self.query()
        self._channels = info[2]
        self._samples = info[1]
        return self

    def copy_existing(self, buffer):
        """Duplicate an existing buffer

        Parameters
        ----------
        buffer: Buffer object
            Buffer which should be duplicated

        Returns
        -------
        self : Buffer
            the newly created Buffer object
        """

        # If both buffers use the same server -> copy buffer directly in the server
        if self.server is buffer.server:
            self.alloc(buffer.samples, buffer.sr, buffer.channels)
            self.gen_copy(buffer, 0, 0, -1)
        else:
            # both sc instance must have the same file server
            self._sr = buffer.sr
            filepath = f"./temp/temp_export_{str(buffer.bufnum)}.wav"
            buffer.write(filepath)
            self.read(filepath)

        self._alloc_mode = 'copy'
        return self

    # Section: Buffer modification methods
    def fill(self, start=0, count=0, value=0):
        """Fill range of samples with value(s).

        Parameters
        ----------
        start: int or list
            int: sample starting index
            list: n*[start, count, value] list
        count: int
            number of samples to fill
        value: float
            value

        Returns
        -------
        self : Buffer
            the created Buffer object
        """
        if self._allocated is False:
            raise RuntimeError("Buffer object is not initialized!")

        if not isinstance(start, list):
            values = [start, count, value]
        else:
            values = start
        self.server.msg("/b_fill", [self._bufnum] + values)
        return self

    def gen(self, command, args):
        """Call a command to fill a buffer.
        If you know, what you do -> you can use this method.

        See Also
        --------
        gen_sine1, gen_sine2, gen_cheby, gen_cheby, gen_copy

        Parameters
        ----------
        command
        args

        Returns
        -------
        self : Buffer
            the created Buffer object
        """
        if self._allocated is False:
            raise RuntimeError("Buffer object is not initialized!")
        self.server.msg("/b_gen", [self._bufnum, command] + args)
        return self

    def zero(self):
        """Free buffer data.

        Returns
        -------
        self : Buffer
            the created Buffer object
        """
        if self._allocated is False:
            raise RuntimeError("Buffer object is not initialized!")
        self.server.msg("/b_zero", [self._bufnum])
        return self

    def gen_sine1(self, amplitudes: list, normalize=False, wavetable=False,
                  clear=False):
        """Fill the buffer with sine waves & given amplitude

        Parameters
        ----------
        amplitudes: List
            The first float value specifies the amplitude of the first partial,
            the second float value specifies the amplitude of the second
            partial, and so on.
        normalize: Bool
            Normalize peak amplitude of wave to 1.0.
        wavetable: Bool
            If set, then the buffer is written in wavetable format so that it
            can be read by interpolating oscillators.
        clear: Bool
            If set then the buffer is cleared before new partials are written
            into it. Otherwise the new partials are summed with the existing
            contents of the buffer

        Returns
        -------
        self : Buffer
            the created Buffer object
        """
        return self.gen("sine1",
                        [self._gen_flags(normalize, wavetable, clear),
                         amplitudes])

    def gen_sine2(self, freq_amps: list, normalize=False, wavetable=False,
                  clear=False):
        """Fill the buffer with sine waves
        given list of [frequency, amplitude] lists

        Parameters
        ----------
        freq_amps: List
            Similar to sine1 except that each partial frequency is specified
            explicitly instead of being an integer multiple of the fundamental.
            Non-integer partial frequencies are possible.
        normalize: Bool
            If set, normalize peak amplitude of wave to 1.0.
        wavetable: Bool
            If set, the buffer is written in wavetable format so that it
            can be read by interpolating oscillators.
        clear: Bool
            If set, the buffer is cleared before new partials are written
            into it. Otherwise the new partials are summed with the existing
            contents of the buffer.

        Returns
        -------
        self : Buffer
            the created Buffer object
        """
        return self.gen("sine2",
                        [self._gen_flags(normalize, wavetable, clear),
                         freq_amps])

    def gen_sine3(self, freqs_amps_phases: list, normalize=False,
                  wavetable=False, clear=False):
        """Fill the buffer with sine waves & given a list of
        [frequency, amplitude, phase] entries.

        Parameters
        ----------
        freqs_amps_phases : List
            Similar to sine2 except that each partial may have a
            nonzero starting phase.
        normalize : Bool
            if set, normalize peak amplitude of wave to 1.0.
        wavetable : Bool
            If set, the buffer is written in wavetable format
            so that it can be read by interpolating oscillators.
        clear: Bool
            If set, the buffer is cleared before new partials are written
            into it. Otherwise the new partials are summed with the existing
            contents of the buffer.

        Returns
        -------
        self : Buffer
            the created Buffer object
        """
        return self.gen("sine3", [self._gen_flags(normalize, wavetable, clear),
                                  freqs_amps_phases])

    def gen_cheby(self, amplitudes: list, normalize=False, wavetable=False,
                  clear=False):
        """Fills a buffer with a series of chebyshev polynomials, which can be
        defined as cheby(n) = amplitude * cos(n * acos(x))

        Parameters
        ----------
        amplitudes : List
            The first float value specifies the amplitude for n = 1,
            the second float value specifies the amplitude
            for n = 2, and so on
        normalize : Bool
            If set, normalize the peak amplitude of the Buffer to 1.0.
        wavetable : Bool
            If set, the buffer is written in wavetable format so that it
            can be read by interpolating oscillators.
        clear: Bool
            If set the buffer is cleared before new partials are written
            into it. Otherwise the new partials are summed with the existing
            contents of the buffer.

        Returns
        -------
        self : Buffer
            the created Buffer object
        """
        return self.gen("cheby", [self._gen_flags(normalize, wavetable, clear),
                                  amplitudes])

    def gen_copy(self, source, source_pos, dest_pos, copy_amount):
        """Copy samples from the source buffer to the destination buffer
        specified in the b_gen command.

        Parameters
        ----------
        source: Buffer
            Source buffer object
        source_pos: int
            sample position in source
        dest_pos: int
            sample position in destination
        copy_amount: int
            number of samples to copy. If the number of samples to copy is
            negative, the maximum number of samples
            possible is copied.

        Returns
        -------
        self : Buffer
            the created Buffer object
        """
        return self.gen("copy", [dest_pos, source.bufnum, source_pos,
                                 copy_amount])

    # Section: Buffer output methods
    def play(self, rate=1, loop=False, pan=0, amp=0.3):
        """Play the Buffer using a Synth

        Parameters
        ----------
        rate : int, optional
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
        if self._allocated is False:
            raise RuntimeError("Buffer object is not initialized!")

        playbuf_def = """
        { |out=0, bufnum=^bufnum, rate=^rate, loop=^loop, pan=^pan, amp=^amp |
                var sig = PlayBuf.ar(^num_channels, bufnum,
                    rate*BufRateScale.kr(bufnum),
                    loop: loop,
                    doneAction: Done.freeSelf);
                Out.ar(out, Pan2.ar(sig, pan, amp))
        }"""

        if self._synth_def is None:
            self._synth_def = sc3nb.SynthDef(
                name=f"sc3nb_playbuf_{self.bufnum}",
                definition=playbuf_def)
            synth_name = self._synth_def.add(
                pyvars={"num_channels": self.channels,
                        "bufnum": self.bufnum,
                        "rate": rate,
                        "loop": 1 if loop else 0,
                        "pan": pan,
                        "amp": amp})
            self._synth = sc3nb.Synth(name=synth_name, server=self.server)
        else:
            self._synth.new(
                {"rate": rate, "loop": 1 if loop else 0,
                 "pan": pan, "amp": amp})
        return self._synth

    def write(self, path, header="wav", sample="float",
              num_frames=-1, starting_frame=0, leave_open=False):
        """Write buffer data to a sound file

        Parameters
        ----------
        path: string
            path name of a sound file.
        header: string
            header format. Header format is one of:
            "aiff", "next", "wav", "ircam"", "raw"
        sample: string
            sample format. Sample format is one of:
            "int8", "int16", "int24", "int32",
            "float", "double", "mulaw", "alaw"
        num_frames: int
            number of frames to write.
            -1 means all frames.
        starting_frame: int
            starting frame in buffer
        leave_open: boolean
            Whether you want the buffer file left open.
            For use with DiskOut you will want this to be true.
            The file is created, but no frames are written until the DiskOut ugen does so.
            The default is false which is the correct value for all other cases.

        Returns
        -------
        self : Buffer
            the Buffer object
        """
        if self._allocated is False:
            raise RuntimeError("Buffer object is not initialized!")
        leave_open_val = 1 if leave_open else 0
        self.server.msg("/b_write", [self._bufnum, path, header, sample,
                                     num_frames, starting_frame, leave_open_val])
        return self

    def close(self):
        """Close soundfile after using a Buffer with DiskOut

        Returns
        -------
        self : Buffer
            the Buffer object
        """
        self.server.msg("/b_close", [self._bufnum], bundled=True)
        return self

    def to_array(self):
        """Return the buffer data as an array representation.

        Returns
        -------
        array :
            Values of the buffer
        """
        data = []
        blocksize = 1000  # array size compatible with OSC packet size
        i = 0
        num_samples = (self._samples * self._channels)
        while i < num_samples:
            bs = blocksize if i+blocksize < num_samples else num_samples-i
            tmp = self.server.msg("/b_getn", [self._bufnum, i, bs])
            data += list(tmp)[3:]  # skip first 3 els [bufnum, startidx, size]
            i += bs
        data = np.array(data).reshape((-1, self._channels))
        return data

    # Section: Buffer information methods
    def query(self):
        """Get buffer info.

        Returns
        -------
        Tuple:
            (buffernumber, number of frames, number of channels, sample rate)
        """
        if self._allocated is False:
            raise RuntimeError("Buffer object is not initialized!")
        return self.server.msg("/b_query", [self._bufnum])

    def _repr_pretty_(self, p, cycle):
        if cycle:
            p.text("Buffer {self.bufnum}")
        else:
            p.text(f"Buffer {self.bufnum} on {self.server.addr}: " + \
                   f"{self.channels} x {self.samples} @ {self.sr} Hz –> " + \
                   f"""{["not loaded", "allocated"][self.allocated]} """ + \
                   f"using mode '{self._alloc_mode}'")

    # Section: Methods to delete / free Buffers
    def free(self):
        """Free buffer data. - The Buffer object both in python and sc will continue to exist!"""
        if self._allocated is False:
            raise RuntimeError("Buffer object is not initialized!")
        self.server.msg("/b_free", [self._bufnum])
        self._allocated = False
        self._alloc_mode = None

    def __del__(self):
        if self._alloc_mode == 'data' and isinstance(self._tempfile, str):
            os.remove(self._tempfile)
        if self._allocated:
            self.free()

    # Section: Properties
    @property
    def bufnum(self):
        """Buffer number which serves as ID in SuperCollider

        Returns
        -------
        int
            bufnum
        """
        return self._bufnum

    @property
    def allocated(self):
        """Whether this Buffer is allocated by
        any of the initialization methods.

        Returns
        -------
        bool
            True if allocated
        """
        return self._allocated

    @property
    def alloc_mode(self):
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
    def tempfile(self):
        """File path of temporary buffer file.

        Returns
        -------
        str
            temporary file path
        """
        return self._tempfile

    @property
    def path(self):
        """File path that was provided to read.

        Returns
        -------
        str
            buffer file path
        """
        return self._path

    @property
    def channels(self):
        """Number of channels in the Buffer.

        Returns
        -------
        int
            channel number
        """
        return self._channels

    @property
    def samples(self):
        """Number of samples in the buffer.

        Returns
        -------
        int
            sample number
        """
        return self._samples

    @property
    def sr(self):
        """Sampling rate of the Buffer.

        Returns
        -------
        int
            sampling rate
        """
        return self._sr

    @property
    def duration(self):
        """Duration of the Buffer in seconds.

        Returns
        -------
        float
            duration in seconds
        """
        return self._samples / self._sr

    # Section: Private utils
    def _gen_flags(self, a_normalize=False, a_wavetable=False, a_clear=False):
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
