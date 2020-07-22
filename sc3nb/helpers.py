"""Collection of helper functions for the user"""
import numpy as np


def linlin(x, smi, sma, dmi, dma):
    """map x linearly so that [smi, sma] is mapped to [dmi, dma]

    Arguments:
        x {float} -- value to be mapped, can be a numpy array
        smi {float} -- source minimum value
        sma {float} -- source maximumn value
        dmi {float} -- destination minimum value
        dma {float} -- destination maximum value

        The description is a bit misleading as now clipping is performed,
        so the function extrapolates. Furthermore it is not forbidden to
        use smi>sma (resp. dmi>dma). The function is defined in analogy to
        SuperCollider3 .linlin.

    Returns:
        float -- the mapping result
    """

    return (x-smi)/(sma-smi)*(dma-dmi) + dmi


def midicps(m):
    """TODO

    Arguments:
        m {int} -- [description]

    Returns:
        float -- [description]
    """

    return 440.0*2**((m-69)/12.0)


def cpsmidi(c):
    """TODO

    Arguments:
        c {float} -- [description]

    Returns:
        float -- [description]
    """

    return 69+12*np.log2(c/440.0)


def clip(value, minimum=-float("inf"), maximum=float("inf")):
    """Clips a value to a certain range

    Arguments:
        value {float} -- Value to clip

    Keyword Arguments:
        minimum {float} -- Minimum value output can take
                           (default: {-float("inf")})
        maximum {float} -- Maximum value output can take
                            (default: {float("inf")})

    Returns:
        float -- clipped value
    """

    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def dbamp(db):
    """TODO

    Arguments:
        db {[type]} -- [description]

    Returns:
        [type] -- [description]
    """

    return 10**(db/20.0)


def ampdb(amp):
    """TODO

    Arguments:
        amp {[type]} -- [description]

    Returns:
        [type] -- [description]
    """

    return 20*np.log10(amp)
