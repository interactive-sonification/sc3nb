"""Collection of helper functions for the user"""
import numpy as np


def linlin(x, x1, x2, y1, y2):
    """map x linearly so that [x1, x2] is mapped to [y1, y2]

    Arguments:
        x {float} -- value to be mapped, can be a numpy array
        x1 {float} -- source value 1
        x2 {float} -- source value 2
        y1 {float} -- destination value to be reached for x==x1
        y2 {float} -- destination value to be reached for x==x2

        linlin is implemented in analogy to the SC3 linlin, yet this
        function extrapolates by default.
        A frequently used invocation is with x1 < x2, i.e. thinking 
        of them as a range [x1,x2]

    Returns:
        float -- the mapping result
    """

    return (x-x1)/(x2-x1)*(y2-y1) + y1


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
