import scipy as sp
import os
import scipy.io.wavfile
from random import randint


class Buffer:
    """
    Initialize a buffer. You can choose:
    b = Buffer(sr*) -> empty buffer, which is not initialized in SC, create it afterwards with b.file(...), b.alloc(...) etc.
    b = Buffer(data, datamode*, sr*) -> create a buffer out of a numpy array
    b = Buffer(path, sr*) -> create a buffer out of a .wav file
    b = Buffer(size, sr*) -> Create an empty buffer with given size
    * Optinal parameter

    when you pass asyncron = True and create a buffer while initialization, the initialization will wait until is the buffer is created in SC
    """
    def __init__(self, sc, sr=44100, data=None, size=None, datamode=None, path=None, bufmode=None, asyncron=False):
        self._bufnum = randint(0, 100000)  #ToDo: Better num handling: use nextNodeID after PR
        self.sc = sc
        self.sr = sr
        self._bufmode = bufmode
        self._loaded = False
        self._tempfile = None
        self._path = None

        if bufmode == 'file':
            Buffer.file(self, path)
        if bufmode == 'alloc':
            Buffer.alloc(self, size)
        if bufmode == 'data':
            Buffer.data(self, data, datamode)

        if asyncron:
            return self.sc.client.recv()

    # Section: Initialization
    def file(self, path):
        self._bufmode = 'file'
        self._path = path
        self.sc.msg("/b_allocRead", [self._bufnum, path])
        self._loaded = True

    def alloc(self, size):
        self._bufmode = 'alloc'
        self.sc.msg("/b_alloc", [self._bufnum, size])
        self._loaded = True

    def data(self, data, mode='file'):
        self._bufmode = 'data'
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

    # Section: Modify buffer
    def fill(self, start, count, value):
        if self._loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_fill", [self._bufnum, [start, count, value]])

    def custom_command(self, command):
        if self._loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_gen", [self._bufnum, command])

    # Section: Output
    def play(self, synth="pb", loop=False):
        if self._loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/s_new", [synth, -1, 1, 0, "bufnum", self._bufnum, "rate", self.sr, "loop", 1 if loop else 0])

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
        return "Buffer(sc, sr=" + str(self.sr) + ", bufmode=" + str(self._bufmode) + ") \r\n Loaded=" + str(self._loaded) + \
               " \r\n Bufnum=" + str(self._bufnum) + \
               " \r\n To see more information about the buffer data, use Buffer.info()"

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
