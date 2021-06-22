"""Collection of helper functions for the user"""
from typing import Optional, Union

import numpy as np


def linlin(
    value: Union[float, np.ndarray],
    x1: float,
    x2: float,
    y1: float,
    y2: float,
    clip: Optional[str] = None,
) -> Union[float, np.ndarray]:
    """Map value linearly so that [x1, x2] is mapped to [y1, y2]

    linlin is implemented in analogy to the SC3 linlin, yet this
    function extrapolates by default.
    A frequently used invocation is with x1 < x2, i.e. thinking
    of them as a range [x1,x2]

    Parameters
    ----------
    value : float or np.ndarray
        value(s) to be mapped
    x1 : float
        source value 1
    x2 : float
        source value 2
    y1 : float
        destination value to be reached for value == x1
    y2 : float
        destination value to be reached for value == x2
    clip: None or string
        None extrapolates, "min" or "max" clip at floor resp. ceiling
        of the destination range, any other value defaults to "minmax",
        i.e. it clips on both sides.

    Returns
    -------
    float or np.ndarray
        the mapping result
    """
    z = (value - x1) / (x2 - x1) * (y2 - y1) + y1
    if clip is None:
        return z
    if y1 > y2:
        x1, x2, y1, y2 = x2, x1, y2, y1
    if clip == "max":
        return np.minimum(z, y2)
    elif clip == "min":
        return np.maximum(z, y1)
    else:  # imply clip to be "minmax"
        return np.minimum(np.maximum(z, y1), y2)


def clip(
    value: float, minimum: float = -float("inf"), maximum: float = float("inf")
) -> float:
    """Clips a value to a certain range

    Parameters
    ----------
    value : float
        Value to clip
    minimum : float, optional
        Minimum output value, by default -float("inf")
    maximum : float, optional
        Maximum output value, by default float("inf")

    Returns
    -------
    float
        clipped value
    """
    if value < minimum:
        return minimum
    if value > maximum:
        return maximum
    return value


def midicps(midi_note: float) -> float:
    """Convert MIDI note to cycles per second

    Parameters
    ----------
    m : float
        midi note

    Returns
    -------
    float
        corresponding cycles per seconds
    """
    return 440.0 * 2 ** ((midi_note - 69) / 12.0)


def cpsmidi(cps: float) -> float:
    """Convert cycles per second to MIDI note

    Parameters
    ----------
    cps : float
        cycles per second

    Returns
    -------
    float
        corresponding MIDI note
    """
    return 69 + 12 * np.log2(cps / 440.0)


def dbamp(decibels: float) -> float:
    """Convert a decibels to a linear amplitude.

    Parameters
    ----------
    decibels : float
        Decibel value to convert

    Returns
    -------
    float
        Corresponding linear amplitude
    """
    return 10 ** (decibels / 20.0)


def ampdb(amp: float) -> float:
    """Convert a linear amplitude to decibels.

    Parameters
    ----------
    amp : float
        Linear amplitude to convert

    Returns
    -------
    float
        Corresponding decibels
    """
    return 20 * np.log10(amp)
