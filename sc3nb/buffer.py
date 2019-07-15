import scipy as sp
import os
import scipy.io.wavfile
import numpy as np


class Buffer:

    """
    A Buffer object represents a SuperCollider3 Buffer on scsynth
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
    sr : int
        the sampling rate of the buffer
    _channels: int
        nr of channels of the buffer
    _samples: int
        buffer length = nr. of sample frames
    _bufnum : int
        buffer number = bufnum id on scsynth
    _alloc_mode : str
        ['file', 'alloc', 'data', 'existing', 'copy']
        according to previously used generator, defaults to None 
    _path : string
        path to a audio file as used in load_file()
    _tempfile : string
        filename (if created) of temporary file used for data transfer to scsynth
    _allocated : boolean
        flagged True if Buffer has been allocated by
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

    Raises
    ------
    Exception: [description]

    Returns
    -------
    self : object of type Buffer
        the created Buffer object

    """

    def __init__(self, sc, bufnum=None):
        if bufnum is None:
            self._bufnum = sc.nextBufferID()
        else:  # force given bufnum
            self._bufnum = bufnum
        self.sc = sc
        self.sr = None
        self._channels = None
        self._samples = None
        self._alloc_mode = None
        self._allocated = False
        self._tempfile = None
        self._path = None

    # Section: Buffer initialization methods
    def load_file(self, path):
        """
        Allocate buffer space and read a sound file.

        Parameters
        ----------
        path: string
            path name of a sound file.

        Returns
        -------
        self : object of type Buffer
            the created Buffer object
        """
        self._alloc_mode = 'file'
        file = sp.io.wavfile.read(path)
        self.sr = file[0]
        self._samples = file[1].shape[0]
        self._channels = 1 if len(file[1].shape) == 1 else file[1].shape[1]
        self._path = path
        self.sc.msg("/b_allocRead", [self._bufnum, path])
        self._allocated = True
        return self

    def alloc(self, size, sr=44100, channels=1):
        """
        Allocate buffer space.

        Parameters
        ----------
        size: int
            number of frames
        sr: int
            number of sampling rate (optional. default = 44100)
        channels: int
            number of channels (optional. default = 1 channel)

        Returns
        -------
        self : object of type Buffer
            the created Buffer object
        """
        self.sr = sr
        self._alloc_mode = 'alloc'
        self._channels = channels
        self._samples = int(size)
        self.sc.msg("/b_alloc", [self._bufnum, size, channels])
        self._allocated = True
        return self

    def load_data(self, data, mode='file', sr=44100):
        """
        Allocate buffer space and read input data.

        Parameters
        ----------
        data: numpy array
            Data which should inserted
        mode: string='file'
            Insert data via filemode or set commands
        sr: int=44100
            sample rate

        Returns
        -------
        self : object of type Buffer
            the created Buffer object
        """
        self._alloc_mode = 'data'
        self.sr = sr
        self._samples = data.shape[0]
        self._channels = 1 if len(data.shape) == 1 else data.shape[1]
        if mode == 'file':
            if not os.path.exists('./temp/'):
                os.makedirs('./temp/')
            self._tempfile = f"./temp/temp_{self._bufnum}.wav"
            sp.io.wavfile.write(self._tempfile, self.sr, data)
            self.sc.msg("/b_allocRead", [self._bufnum, self._tempfile])
        else:
            self.sc.msg("/b_alloc", [self._bufnum, data.shape[0]])
            blocksize = 1000 # array size compatible with OSC packet size
            # TODO: check how this depends on datagram size
            # TODO: put into Buffer header as const if needed elsewhere...
            if data.shape[0] < blocksize:
                self.sc.msg("/b_setn", [self._bufnum, [0, data.shape[0], data.tolist()]])
            else:
                # For datasets larger than {blocksize} entries, split data to avoid network problems
                splitdata = np.array_split(data, data.shape[0]/blocksize)
                for i, tData in enumerate(splitdata):
                    self.sc.msg("/b_setn", [self._bufnum, [i * blocksize, tData.shape[0], tData.tolist()]])
        self._allocated = True
        return self

    def load_collection(self, data, mode='file', sr=44100):
        """
        Wrapper method of :func:`Buffer.load_data`
        """
        self.load_data(data, mode, sr)
        return self

    def load_asig(self, asig, mode='file'):
        # ToDo: issue warning is not isinstance(asig, pya.Asig)
        self.load_data(asig.sig, mode, sr=asig.sr)
        return self

    def use_existing(self, bufnum, sr=44100):
        """
        Creates a buffer object from already existing Buffer bufnum.

        Parameters
        ----------
        bufnum: int
            buffer node id
        sr: int
            Sample rate

        Returns
        -------
        self : object of type Buffer
            the created Buffer object
        """
        self._alloc_mode = 'existing'
        self.sr = sr
        self._bufnum = bufnum
        self._allocated = True
        data = self.sc.msg("/b_query", [self._bufnum])
        self._channels = data[2]
        self._samples = data[1]
        return self

    def copy_existing(self, buffer):
        """
        Duplicate a existing buffer

        Parameters
        ----------
        buffer: Buffer obj
            Buffer which should duplicated

        Returns
        -------
        self : object of type Buffer
            the created Buffer object
        """

        # If both buffers use the same sc instance -> copy buffer directly in sc
        if self.sc == buffer.sc:
            self.alloc(buffer.samples, buffer.sr, buffer.channels)
            self.gen_copy(buffer, 0, 0, -1)
        else:
            # both sc instance must have the same file server
            self.sr = buffer.sr
            filepath = f"./temp/temp_export_{str(buffer.bufnum)}.wav"
            buffer.write(filepath)
            self.load_file(filepath)

        self._alloc_mode = 'copy'
        return self

    # Section: Buffer modification methods
    def fill(self, start, count=0, value=0):
        """
        Fill ranges of sample value(s).

        Parameters
        ----------
        start: int/ list
            int: sample starting index
            list: n*[start, count, value] list
        count: int
            number of samples to fill
        value: float
            value

        Returns
        -------
        self : object of type Buffer
            the created Buffer object
        """
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")

        if type(start) != list:
            values = [start, count, value]
        else:
            values = start
        self.sc.msg("/b_fill", [self._bufnum] + values)
        return self

    def gen(self, command, args):
        """
        Call a command to fill a buffer. 
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
        self : object of type Buffer
            the created Buffer object
        """
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_gen", [self._bufnum, command] + args)
        return self

    def zero(self):
        """
        Free buffer data.

        Returns
        -------
        self : object of type Buffer
            the created Buffer object
        """
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_zero", [self._bufnum])
        return self

    def gen_sine1(self, amplitudes: list, normalize=False, wavetable=False, clear=False):
        """
        Fill the buffer with sine waves & given amplitude

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
        self : object of type Buffer
            the created Buffer object
        """
        return self.gen("sine1", [self._gen_flags(normalize, wavetable, clear), amplitudes])

    def gen_sine2(self, freq_amps: list, normalize=False, wavetable=False, clear=False):
        """
        Fill the buffer with sine waves & given list of [frequency, amplitude] lists

        Parameters
        ----------
        freq_amps: List
            Similar to sine1 except that each partial frequency is specified
            explicitly instead of being an integer series of partials.
            Non-integer partial frequencies are possible.
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
        self : object of type Buffer
            the created Buffer object
        """
        return self.gen("sine2", [self._gen_flags(normalize, wavetable, clear), freq_amps])

    def gen_sine3(self, freq_amps_phase: list, normalize=False, wavetable=False, clear=False):
        """
        Fill the buffer with sine waves & given a list of 
        [frequency, amplitude, phase] entries.

        Parameters
        ----------
        freq_amps_phase : List
            Similar to sine2 except that each partial may have a
            nonzero starting phase.
        normalize : Bool
            Normalize peak amplitude of wave to 1.0.
        wavetable : Bool
            If set, then the buffer is written in wavetable format
            so that it can be read by interpolating oscillators.
        clear: Bool
            If set then the buffer is cleared before new partials are written
            into it. Otherwise the new partials are summed with the existing
            contents of the buffer

        Returns
        -------
        self : object of type Buffer
            the created Buffer object
        """
        return self.gen("sine3", [self._gen_flags(normalize, wavetable, clear), freq_amps_phase])

    def gen_cheby(self, amplitude: list, normalize=False, wavetable=False, clear=False):
        """
        Fills a buffer with a series of chebyshev polynomials, which can be
        defined as cheby(n) = amplitude * cos(n * acos(x))

        Parameters
        ----------
        amplitude : List
            The first float value specifies the amplitude for n = 1,
            the second float value specifies the amplitude
            for n = 2, and so on
        normalize : Bool
            Normalize peak amplitude of wave to 1.0.
        wavetable : Bool
            If set, then the buffer is written in wavetable format so that it
            can be read by interpolating oscillators.
        clear: Bool
            If set then the buffer is cleared before new partials are written
            into it. Otherwise the new partials are summed with the existing 
            contents of the buffer.

        Returns
        -------
        self : object of type Buffer
            the created Buffer object
        """
        return self.gen("cheby", [self._gen_flags(normalize, wavetable, clear), amplitude])

    def gen_copy(self, source, source_pos, dest_pos, copy_amount):
        """
        Copy samples from the source buffer to the destination buffer
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
        self : object of type Buffer
            the created Buffer object
        """
        return self.gen("copy", [dest_pos, source.bufnum, source_pos, copy_amount])

    # Section: Buffer output methods
    def play(self, synth="pb-1ch", rate=1, loop=False, pan=0, amp=0.3):
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        id = self.sc.nextNodeID()
        self.sc.msg("/s_new", [
                synth, id, 1, 1,
                "bufnum", self._bufnum,
                "rate", rate,
                "loop", 1 if loop else 0,
                "pan", pan,
                "amp", amp
            ])
        return id

    def write(self, path, header="wav", sample="float"):
        """
        Write buffer data to a sound file

        Parameters
        ----------
        path: string
            path name of a sound file.
        header: string
            header format. Header format is one of:
            "aiff", "next", "wav", "ircam"", "raw"
        sample: string
            sample format. Sample format is one of:
            "int8", "int16", "int24", "int32", "float", "double", "mulaw", "alaw"

        Returns
        -------
        self : object of type Buffer
            the created Buffer object
        """
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_write", [self._bufnum, path, header, sample, -1, 0, 0])
        return self

    def to_array(self):
        """
        Return the buffer data as an array representation.

        Returns
        -------
        array :
            Values of the buffer
        """
        data = []
        blocksize = 1000  # array size compatible with OSC packet size
        i = 0
        while i < self._samples:
            bs = blocksize if i+blocksize < self._samples else self._samples-i 
            tmp = self.sc.msg("/b_getn", [self._bufnum, i, bs])
            data += list(tmp)[3:]  # skip first 3 els [bufnum, startidx, size]
            i += bs
        return np.array(data)

    # Section: Buffer information methods
    def query(self):
        """
        Get buffer info.

        Returns
        -------
        Tuple:
            (buffernumber, number of frames, number of channels, sample rate)
        """
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        return self.sc.msg("/b_query", [self._bufnum])

    def __repr__(self):
        return f"Buffer {self._bufnum} on sc {self.sc.osc.sclang_address}: "+ \
            f"{self._channels} x {self._samples} @ {self.sr} Hz –> "+ \
            f"""{["not loaded", "allocated"][self._allocated]} """+ \
            f"using mode '{self._alloc_mode}'"

    # Section: Methods to delete / free Buffers
    def free(self):
        """
        Free buffer data. - The buffer object in sc will still exists!
        """
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_free", [self._bufnum])
        self._allocated = False
        if self._alloc_mode == 'data' and isinstance(self._tempfile, str):
            os.remove(self._tempfile)
        self._alloc_mode = None

    def __del__(self):
        self.free()

    # Section: Properties
    @property
    def bufnum(self):
        return self._bufnum

    @property
    def allocated(self):
        return self._allocated

    @property
    def alloc_mode(self):
        return self._alloc_mode

    @property
    def tempfile(self):
        return self._tempfile

    @property
    def path(self):
        return self._path

    @property
    def channels(self):
        return self._channels

    @property
    def samples(self):
        return self._samples

    # Section: Private utils
    def _gen_flags(self, a_normalize=False, a_wavetable=False, a_clear=False):
        normalize = 1 if a_normalize is True else 0
        wavetable = 2 if a_wavetable is True else 0
        clear = 4 if a_clear is True else 0
        return normalize + wavetable + clear
