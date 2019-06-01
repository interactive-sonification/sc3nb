import scipy as sp
import os
import scipy.io.wavfile
import numpy as np
import time

# ToDo: Add blocking to all loader


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
        The server instance to establish the Buffer to 

    Attributes
    ----------
    sc : the SC object 
        to communicate with scsynth
    sr : int
        the sampling rate of the buffer
    bufnum : int
        buffer number = bufnum id on scsynth
    bufmode : {'file', 'osc'}
        transport mode for data from python to scsynth. Defaults to 'file'
    path : string
        path to a audio file as used in load_file()
    tempfile : string
        filename (if created) of temporary file used for data transfer to scsynth
    allocated : boolean
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
    has been added to class SC which forwards self to calling 
    the Buffer constructor, allowing instead to write
        b1 = sc.Buffer().alloc(44100)

    Examples
    --------
    b = Buffer().load_file(...)
    b = Buffer().load_data(...)
    b = Buffer().alloc(...)
    b = Buffer().load_pya(...)
    b = Buffer().load_existing(...)
    b = Buffer().copy(Buffer)

    Raises
    ------
    Exception: [description]
    
    Returns
    -------
    self : object of type Buffer
        the created Buffer object
    
    """

    def __init__(self, sc):
        self._bufnum = sc.nextBufferID()
        self.sc = sc
        self.sr = None
        self._bufmode = None
        self._allocated = False
        self._tempfile = None
        self._path = None

    # Section: Buffer initialization methods
    def load_file(self, path):
        self._bufmode = 'file'
        file = sp.io.wavfile.read(path)
        self.sr = file[0]
        self._path = path
        self.sc.msg("/b_allocRead", [self._bufnum, path])
        self._allocated = True
        return self

    def alloc(self, size, sr=44100):
        self.sr = sr
        self._bufmode = 'alloc'
        self.sc.msg("/b_alloc", [self._bufnum, size])
        self._allocated = True
        return self

    def load_data(self, data, mode='file', sr=44100):
        self._bufmode = 'data'
        self.sr = sr
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
        self.load_data(data, mode, sr)
        return self

    def load_pya(self, pya, mode='file'):
        Buffer.data(self, pya.asic, mode, sr=pya.sample_rate)
        return self

    def load_existing(self, bufnum, sr=44100):
        self._bufmode = 'existing'
        self.sr = sr
        self._bufnum = bufnum
        self._allocated = True
        return self

    def copy_existing(self, buffer):
        self._bufmode = 'copy'
        self.sr = buffer.sr
        filepath = f"./temp/temp_export_{str(buffer.bufnum)}.wav"
        buffer.write(filepath)
        time.sleep(5)  # ToDo: When sync problem is fixed, use sc.sync() to wait for done instead of wait random 5s
        self.load_file(filepath)
        return self

    # Section: Buffer modification methods
    def fill(self, start, count, value):
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_fill", [self._bufnum, [start, count, value]])
        return self

    def gen(self, command, args):
        """
        Call a command to fill a buffer. If you know, what you do -> you can use this method.
        Otherwhise following wrapper exist:
        :see gen_sine1, gen_sine2, gen_cheby, gen_cheby, gen_copy
        :param command:
        :param args:
        :return:
        """
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_gen", [self._bufnum, command] + args)
        return self

    def zero(self):
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_zero", [self._bufnum])
        return self

    def gen_sine1(self, amplitudes: list, normalize=False, wavetable=False, clear=False):
        """
        Fill the buffer with sinus waves & given amplitude
        :param amplitudes:  List: The first float value specifies the amplitude of the first partial, the second float
                            value specifies the amplitude of the second partial, and so on.
        :param normalize:   Bool: Normalize peak amplitude of wave to 1.0.
        :param wavetable:   Bool: If set, then the buffer is written in wavetable format so that it can be read
                            by interpolating oscillators.
        :param clear:       Bool: If set then the buffer is cleared before new partials are written into it. Otherwise
                            the new partials are summed with the existing contents of the buffer
        :return:            self
        """
        return self.gen("sine1", [self._gen_flags(normalize, wavetable, clear), amplitudes])

    def gen_sine2(self, freq_amps: list, normalize=False, wavetable=False, clear=False):
        """
        Fill the buffer with sinus waves & given amplitude/ frequency
        :param freq_amps:   List: Similar to sine1 except that each partial frequency is specified explicitly instead of
                            being an integer series of partials. Non-integer partial frequencies are possible.
        :param normalize:   Bool: Normalize peak amplitude of wave to 1.0.
        :param wavetable:   Bool: If set, then the buffer is written in wavetable format so that it can be read
                            by interpolating oscillators.
        :param clear:       Bool: If set then the buffer is cleared before new partials are written into it. Otherwise
                            the new partials are summed with the existing contents of the buffer
        :return:            self
        """
        return self.gen("sine2", [self._gen_flags(normalize, wavetable, clear), freq_amps])

    def gen_sine3(self, freq_amps_phase: list, normalize=False, wavetable=False, clear=False):
        """
        Fill the buffer with sinus waves & given amplitude/ frequency/ phase
        :param freq_amps_phase:   List: Similar to sine2 except that each partial may have a nonzero starting phase.
        :param normalize:   Bool: Normalize peak amplitude of wave to 1.0.
        :param wavetable:   Bool: If set, then the buffer is written in wavetable format so that it can be read
                            by interpolating oscillators.
        :param clear:       Bool: If set then the buffer is cleared before new partials are written into it. Otherwise
                            the new partials are summed with the existing contents of the buffer
        :return:            self
        """
        return self.gen("sine3", [self._gen_flags(normalize, wavetable, clear), freq_amps_phase])

    def gen_cheby(self, amplitude: list, normalize=False, wavetable=False, clear=False):
        """
        Fills a buffer with a series of chebyshev polynomials, which can be defined as
        cheby(n) = amplitude * cos(n * acos(x))

        :param amplitude:   List: The first float value specifies the amplitude for n = 1, the second float value
                            specifies the amplitude for n = 2, and so on
        :param normalize:   Bool: Normalize peak amplitude of wave to 1.0.
        :param wavetable:   Bool: If set, then the buffer is written in wavetable format so that it can be read
                            by interpolating oscillators.
        :param clear:       Bool: If set then the buffer is cleared before new partials are written into it. Otherwise
                            the new partials are summed with the existing contents of the buffer
        :return:            self
        """
        return self.gen("cheby", [self._gen_flags(normalize, wavetable, clear), amplitude])

    def gen_copy(self, source, source_pos, dest_pos, copy_amount):
        """
        Copy samples from the source buffer to the destination buffer specified in the b_gen command
        :param source:      Buffer: Source buffer object
        :param source_pos:  int: sample position in source
        :param dest_pos:    int: sample position in destination
        :param copy_amount: int: number of samples to copy. If the number of samples to copy is negative, the maximum number
                            of samples possible is copied.
        :return:            self
        """
        return self.gen("copy", [dest_pos, source.bufnum, source_pos, copy_amount])

    # Section: Buffer output methods
    def play(self, synth="pb-1ch", rate=1, loop=False, pan=0, amp=0.3):
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        id = self.sc.nextNodeID()
        self.sc.msg("/s_new", [synth, id, 1, 1,
            "bufnum", self._bufnum,
            "rate", rate,
            "loop", 1 if loop else 0,
            "pan", pan,
            "amp", amp
            ])
        return id

    def write(self, path, header="wav", sample="float"):
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_write", [self._bufnum, path, header, sample, -1, 0, 0])
        return self

    # Section: Buffer information methods
    def query(self):
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_query", [self._bufnum])
        # ToDo: Wait for fix sync problem
        return self.sc.client.recv()

    def __repr__(self):
        return f"Buffer(sc=sc, sr={str(self.sr)}, bufmode={str(self._bufmode)}) \r\n Loaded={str(self._allocated)}" + \
               f"\r\n Bufnum={str(self._bufnum)}" + \
                "\r\n To see more information about the buffer data, use Buffer.query()"  # ToDo: Replace sc= with adress to sc server

    # Section: Methods to delete / free Buffers
    def free(self):
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_free", [self._bufnum])
        self._allocated = False
        if self._bufmode == 'data' and isinstance(self._tempfile, str):
            os.remove(self._tempfile)

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
    def bufmode(self):
        return self._bufmode

    @property
    def tempfile(self):
        return self._tempfile

    @property
    def path(self):
        return self._path

    # Section: Private utils
    def _gen_flags(self, a_normalize=False, a_wavetable=False, a_clear=False):
        normalize = 1 if a_normalize is True else 0
        wavetable = 2 if a_wavetable is True else 0
        clear = 4 if a_clear is True else 0
        return normalize + wavetable + clear
