import numpy as np
import scipy as sp
import os
import scipy.io.wavfile
from random import randint


class Buffer:
    def __init__(self, sc, data, sr=44100):
        self.bufnum = randint(0, 100000) # ToDo: Better num handling
        self.sc = sc
        self.sr = sr
        sp.io.wavfile.write('./temp_' + str(self.bufnum), sr, data)
        self.sc.msg("/b_allocRead", [self.bufnum, './temp_' + str(self.bufnum)])
        #print(self.sc.client.recv())

    def play(self, synth="pb"):
        self.sc.msg("/s_new", [synth, -1, 1, 0, "bufnum", self.bufnum, "rate", self.sr])

    def free(self):
        self.sc.msg("/b_free", [self.bufnum])
        os.remove('./temp_' + str(self.bufnum))

    def fill(self, start, count, value):
        self.sc.msg("/b_fill", [self.bufnum, [start, count, value]])

    def write(self, path, header="wav", sample="float"):
        self.sc.msg("/b_write", [self.bufnum, path, header, sample, -1, 0, 0])

    def custom_command(self, command):
        self.sc.msg("/b_gen", [self.bufnum, command])

    def info(self):
        self.sc.msg("/b_query", [self.bufnum])
        # ToDo: Wait for fix sync problem
        return self.sc.client.recv()

    def __del__(self):
        self.free()
