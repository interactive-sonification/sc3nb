import numpy as np
import scipy as sp
import os
import scipy.io.wavfile
from random import randint


class Buffer:
    def __init__(self, sc, data):
        self.bufferId = randint(0,100000)
        self.sc = sc
        sp.io.wavfile.write('./temp_' + str(self.bufferId), 500, data)
        self.sc.msg("/b_allocRead", [self.bufferId, './temp_' + str(self.bufferId)])
       # print(self.sc.client.recv())

    def get_id(self):
        return self.bufferId

    def play(self, synth="pb"):
        self.sc.msg("/s_new", [synth, -1, 1, 0, "bufnum", self.bufferId, "rate", 40])

    def free(self):
        self.sc.msg("/b_free", [self.bufferId])
        os.remove('./temp_' + str(self.bufferId))

    def __del__(self):
        self.free()
