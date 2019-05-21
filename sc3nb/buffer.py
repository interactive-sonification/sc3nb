import scipy as sp
import os
import scipy.io.wavfile
from random import randint
import time

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
    """
    def __init__(self, sc):
        self._bufnum = sc.nextBufferID()
        self.sc = sc
        self.sr = None
        self._bufmode = None
        self._allocated = False
        self._tempfile = None
        self._path = None

    # Section: Initialization
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
            self.sc.msg("/b_setn", [self._bufnum, data.tolist()])
        self._allocated = True
        return self

    def load_collection(self, data, mode='file', sr=44100):
        self.load_data(data, mode, sr)

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

    # Section: Modify buffer
    def fill(self, start, count, value):
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_fill", [self._bufnum, [start, count, value]])

    def gen(self, command):
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_gen", [self._bufnum, command])

    # Section: Output
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

    # Section: Buffer information
    def query(self):
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_query", [self._bufnum])
        # ToDo: Wait for fix sync problem
        return self.sc.client.recv()

    def __repr__(self):
        return f"Buffer(sc, sr={str(self.sr)}, bufmode={str(self._bufmode)}) \r\n Loaded={str(self._allocated)}" + \
               f"\r\n Bufnum={str(self._bufnum)}" + \
                "\r\n To see more information about the buffer data, use Buffer.info()"

    # Section: Delete/ free buffer
    def free(self):
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_free", [self._bufnum])
        if self._bufmode == 'data' and isinstance(self._tempfile, str):
            os.remove(self._tempfile)

    def zero(self):
        if self._allocated is False:
            raise Exception("Buffer object is not initialized yet!")
        self.sc.msg("/b_zero", [self._bufnum])

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
