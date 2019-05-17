import scipy as sp
import os
import scipy.io.wavfile
from random import randint

# ToDo: Add blocking to all loader

class Buffer:
    """
    Initialize a buffer. You have to fill the buffer afterwards:
    b = Buffer().load_file(...)
    b = Buffer().load_data(...)
    b = Buffer().alloc(...)
    b = Buffer().load_pya(...)
    b = Buffer().load_existing(...)
    b = Buffer().copy(Buffer)

    when you pass asyncron = True and create a buffer while initialization, the initialization will wait until is the buffer is created in SC
    """
    def __init__(self, sc):
        self._bufnum = randint(0, 100000)  # ToDo: Better num handling: use nextNodeID after PR
        self.sc = sc
        self.sr = None
        self._bufmode = None
        self._loaded = False
        self._tempfile = None
        self._path = None

    # Section: Initialization
    def load_file(self, path, sr=44100):
        self._bufmode = 'file'
        self.sr = sr # ToDo: Read sr from file, for example: scipy.io.wavfile.read -> rate
        self._path = path
        self.sc.msg("/b_allocRead", [self._bufnum, path])
        self._loaded = True

        return self

    def alloc(self, size, sr=44100):
        self.sr = sr
        self._bufmode = 'alloc'
        self.sc.msg("/b_alloc", [self._bufnum, size])
        self._loaded = True

        return self

    def load_data(self, data, mode='file', sr=44100):
        self._bufmode = 'data'
        self.sr = sr
        if mode == 'file':
            if not os.path.exists('./temp/'):
                os.makedirs('./temp/')
            self._tempfile = './temp/temp_' + str(self._bufnum)
            sp.io.wavfile.write(self._tempfile, self.sr, data)
            self.sc.msg("/b_allocRead", [self._bufnum, self._tempfile])
        else:
            self.sc.msg("/b_alloc", [self._bufnum, data.shape[0]])
            self.sc.msg("/b_setn", [self._bufnum, data.tolist()])
        self._loaded = True
        return self

    def load_pya(self, pya, mode='file'):
        Buffer.data(self, pya.asic, mode, sr=pya.sample_rate)
        return self

    def load_existing(self, bufnum, sr=44100):
        self._bufmode = 'existing'
        self.sr = sr
        self._bufnum = bufnum
        self._loaded = True
        return self

    # Section: Modify buffer
    def fill(self, start, count, value):
        if self._loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_fill", [self._bufnum, [start, count, value]])

    def gen(self, command):
        if self._loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_gen", [self._bufnum, command])

    # Section: Output
    def play(self, synth="pb", rate=1, loop=False):
        if self._loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/s_new", [synth, -1, 1, 0, "bufnum", self._bufnum, "rate", rate, "loop", 1 if loop else 0])

    def write(self, path, header="wav", sample="float"):
        if self._loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_write", [self._bufnum, path, header, sample, -1, 0, 0])

    # Section: Buffer information
    def query(self):
        if self._loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_query", [self._bufnum])
        # ToDo: Wait for fix sync problem
        return self.sc.client.recv()

    def __repr__(self):
        return f"Buffer(sc, sr={str(self.sr)}, bufmode={str(self._bufmode)}) \r\n Loaded={str(self._loaded)}" + \
                "\r\n Bufnum={str(self._bufnum)}" + \
                "\r\n To see more information about the buffer data, use Buffer.info()"

    # Section: Delete/ free buffer
    def free(self):
        if self._loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_free", [self._bufnum])
        if self._bufmode == 'data' and isinstance(self._tempfile, str):
            os.remove(self._tempfile)

    def zero(self):
        if self._loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_zero", [self._bufnum])

    def __del__(self):
        self.free()

    # Section: Properties
    @property
    def bufnum(self):
        return self._bufnum

    @property
    def loaded(self):
        return self._loaded

    @property
    def bufmode(self):
        return self._bufmode

    @property
    def tempfile(self):
        return self._tempfile

    @property
    def path(self):
        return self._path
