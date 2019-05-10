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
        self.bufnum = randint(0, 100000)  #ToDo: Better num handling: use nextNodeID after PR
        self.sc = sc
        self.sr = sr
        self.bufmode = bufmode
        self.loaded = False
        self.tempfile = None
        self.path = None

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
        self.bufmode = 'file'
        self.path = path
        self.sc.msg("/b_allocRead", [self.bufnum, path])
        self.loaded = True

    def alloc(self, size):
        self.bufmode = 'alloc'
        self.sc.msg("/b_alloc", [self.bufnum, size])
        self.loaded = True

    def data(self, data, mode='file'):
        self.bufmode = 'data'
        if mode == 'file':
            if not os.path.exists('./temp/'):
                os.makedirs('./temp/')
            self.tempfile = './temp/temp_' + str(self.bufnum)
            sp.io.wavfile.write(self.tempfile, self.sr, data)
            self.sc.msg("/b_allocRead", [self.bufnum, self.tempfile])
        else:
            self.sc.msg("/b_alloc", [self.bufnum, data.shape[0]])
            self.sc.msg("/b_setn", [self.bufnum, data.tolist()])
        self.loaded = True

    # Section: Modify buffer
    def fill(self, start, count, value):
        if self.loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_fill", [self.bufnum, [start, count, value]])

    def custom_command(self, command):
        if self.loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_gen", [self.bufnum, command])

    # Section: Output
    def play(self, synth="pb"):
        if self.loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/s_new", [synth, -1, 1, 0, "bufnum", self.bufnum, "rate", self.sr])

    def write(self, path, header="wav", sample="float"):
        if self.loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_write", [self.bufnum, path, header, sample, -1, 0, 0])

    # Section: Buffer information
    def query(self):
        if self.loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_query", [self.bufnum])
        # ToDo: Wait for fix sync problem
        return self.sc.client.recv()

    def __repr__(self):
        return "Buffer(sc, sr=" + str(self.sr) + ", bufmode=" + str(self.bufmode) + ") \r\n Loaded=" + str(self.loaded) + \
               " \r\n Bufnum=" + str(self.bufnum) + \
               " \r\n To see more information about the buffer data, use Buffer.info()"

    # Section: Delete/ free buffer
    def free(self):
        if self.loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_free", [self.bufnum])
        if self.bufmode == 'data' and isinstance(self.tempfile, str):
            os.remove(self.tempfile)

    def zero(self):
        if self.loaded is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_zero", [self.bufnum])

    def __del__(self):
        self.free()
