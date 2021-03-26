"""Python representation of the scsynth Bus."""

from enum import Enum, unique

from typing import Optional, Sequence, Union, TYPE_CHECKING

import sc3nb

if TYPE_CHECKING:
    from sc3nb.sc_objects.server import SCServer


@unique
class ControlBusCommand(str, Enum):
    """OSC Commands for Control Buses"""
    FILL = "/c_fill"
    SET = "/c_set"
    SETN = "/c_setn"
    GET = "/c_get"
    GETN = "/c_getn"

@unique
class BusRate(str, Enum):
    """Calculation rate of Buses"""
    AUDIO = "audio"
    CONTROL = "control"


class Bus():
    """Represenation of a Control or Audio Bus on the SuperCollider Server"""

    def __init__(self,
                 rate: Union[BusRate, str],
                 num_channels: int = 1,
                 index: Optional[int] = None,
                 server: Optional['SCServer'] = None
                 ) -> None:
        self._server = server or sc3nb.SC.get_default().server
        self._num_channels = num_channels
        self._rate = rate
        if index is None:
            if self._rate is BusRate.AUDIO:
                self._bus_idxs = self._server.allocate_audio_bus_idx(self._num_channels)
            else:
                self._bus_idxs = self._server.allocate_control_bus_idx(self._num_channels)
        else:
            self._bus_idxs = range(index, index + num_channels)
        if num_channels > 1:
            assert len(self._bus_idxs) == num_channels, "Not enough idxes for number of channels"
        self._bus_idx = self._bus_idxs[0]

    @property
    def rate(self) -> Union[BusRate, str]:
        """The bus calculation rate.

        Returns
        -------
        BusRate
            the rate of this bus
        """
        return self._rate


    @property
    def idx(self) -> int:
        """The (first) bus index.

        Returns
        -------
        int
            first bus index
        """
        return self._bus_idx

    def is_audio_bus(self) -> bool:
        """Rate check

        Returns
        -------
        bool
            True if this is a audio bus
        """
        return self._rate is BusRate.AUDIO

    def is_control_bus(self) -> bool:
        """Rate check

        Returns
        -------
        bool
            True if this is a control bus
        """
        return self._rate is BusRate.CONTROL

    def set(self, value: Union[int, float]) -> None:
        """Set bus value

        Parameters
        ----------
        value : int or float
            Value that should be set

        Raises
        ------
        RuntimeError
            If trying to set an Audio Bus
        """
        if self._rate is BusRate.AUDIO:
            raise RuntimeError("Can't set Audio Buses")
        self._server.msg(ControlBusCommand.SET, [self._bus_idx, value])

    def setn(self, values: Sequence[Union[int, float]], num_buses: Optional[int] = None):
        """Set ranges of bus values.

        Parameters
        ----------
        values : sequence of int or float
            Values that should be set
        num_buses : Optional[int], optional
            how many sequential buses to change, by default same as num_channels

        Raises
        ------
        RuntimeError
            If trying to setn an Audio Bus
        """
        if self._rate is BusRate.AUDIO:
            raise RuntimeError("Can't setn Audio Buses")
        if num_buses is None:
            num_buses = self._num_channels
        self._server.msg(ControlBusCommand.SETN, [self._bus_idx, num_buses, *values])

    def fill(self, value: Union[int, float], num_buses: Optional[int] = None):
        """Fill ranges of buses to one value.

        The range starts at this bus idx

        Parameters
        ----------
        value : Union[int, float]
            [description]
        num_buses : Optional[int], optional
            [description], by default None

        Raises
        ------
        RuntimeError
            [description]
        """
        if self._rate is BusRate.AUDIO:
            raise RuntimeError("Can't fill Audio Buses")
        if num_buses is None:
            num_buses = self._num_channels
        self._server.msg(ControlBusCommand.FILL, [self._bus_idx, num_buses, value])

    def get(self) -> Union[Union[int, float], Sequence[Union[int, float]]]:
        """Get bus value(s).

        Returns
        -------
        bus value or sequence of bus values
            The current value of this bus
            Multiple values if this bus has num_channels > 1

        Raises
        ------
        RuntimeError
            [description]
        """
        if self._rate is BusRate.AUDIO:
            raise RuntimeError("Can't get Audio Buses")
        if self._num_channels > 1:
            return self._server.msg(ControlBusCommand.GETN, [self._bus_idx, self._num_channels])
        else:
            return self._server.msg(ControlBusCommand.GET, [self._bus_idx])

    def free(self) -> None:
        """Mark this Buses ids as free again"""
        if self._rate is BusRate.AUDIO:
            self._bus_idxs = self._server.audio_bus_id_allocator.free_ids(self._bus_idxs)
        else:
            self._bus_idxs = self._server.control_bus_id_allocator.free_ids(self._bus_idxs)

    def __del__(self) -> None:
        self.free()
