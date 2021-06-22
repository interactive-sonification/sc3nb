"""Module for recording"""

from enum import Enum, unique
from typing import Optional, Union

from sc3nb.sc import SC
from sc3nb.sc_objects.buffer import Buffer
from sc3nb.sc_objects.node import AddAction, Node, Synth
from sc3nb.sc_objects.server import SCServer
from sc3nb.sc_objects.synthdef import SynthDef


@unique
class RecorderState(Enum):
    """Different States"""

    UNPREPARED = "UNPREPARED"
    PREPARED = "PREPARED"
    RECORDING = "RECORDING"
    PAUSED = "PAUSED"


class Recorder:
    """Allows to record audio easily."""

    # TODO rec_header, rec_format with Literal type (py3.8) from Buffer
    def __init__(
        self,
        path: str = "record.wav",
        nr_channels: int = 2,
        rec_header: str = "wav",
        rec_format: str = "int16",
        bufsize: int = 65536,
        server: Optional[SCServer] = None,
    ):
        """Create and prepare a recorder.

        Parameters
        ----------
        path : str, optional
            path of recording file, by default "record.wav"
        nr_channels : int, optional
            Number of channels, by default 2
        rec_header : str, optional
            File format, by default "wav"
        rec_format : str, optional
            Recording resolution, by default "int16"
        bufsize : int, optional
            size of buffer, by default 65536
        server : SCServer, optional
            server used for recording,
            by default use the SC default server
        """
        self._state = RecorderState.UNPREPARED
        self._server = server or SC.get_default().server
        self._record_buffer = Buffer(server=self._server)
        self._record_synth: Optional[Synth] = None
        self.prepare(path, nr_channels, rec_header, rec_format, bufsize)

    def prepare(
        self,
        path: str = "record.wav",
        nr_channels: int = 2,
        rec_header: str = "wav",
        rec_format: str = "int16",
        bufsize: int = 65536,
    ):
        """Pepare the recorder.

        Parameters
        ----------
        path : str, optional
            path of recording file, by default "record.wav"
        nr_channels : int, optional
            Number of channels, by default 2
        rec_header : str, optional
            File format, by default "wav"
        rec_format : str, optional
            Recording resolution, by default "int16"
        bufsize : int, optional
            size of buffer, by default 65536

        Raises
        ------
        RuntimeError
            When Recorder does not needs to be prepared.
        """
        if self._state != RecorderState.UNPREPARED:
            raise RuntimeError(
                f"Recorder state must be UNPREPARED but is {self._state}"
            )
        # prepare buffer
        self._record_buffer.alloc(bufsize, channels=nr_channels)
        self._record_buffer.write(
            path=path,
            header=rec_header,
            sample=rec_format,
            num_frames=0,
            starting_frame=0,
            leave_open=True,
        )
        self._rec_id = self._record_buffer.bufnum
        # TODO we could prepare the synthDef beforehand and just use the right one here.
        # This would allow Recordings without sclang
        self._synth_def = SynthDef(
            f"sc3nb_recording_{self._rec_id}",
            r"""{ |bus, bufnum, duration|
            var tick = Impulse.kr(1);
            var timer = PulseCount.kr(tick) - 1;
            Line.kr(0, 0, duration, doneAction: if(duration <= 0, 0, 2));
            SendReply.kr(tick, '/recordingDuration', timer, ^rec_id);
            DiskOut.ar(bufnum, In.ar(bus, ^nr_channels))
        }""",
        )
        self._synth_name = self._synth_def.add(
            pyvars={"rec_id": self._rec_id, "nr_channels": nr_channels}
        )
        self._state = RecorderState.PREPARED

    def start(
        self,
        timetag: float = 0,
        duration: Optional[float] = None,
        node: Union[Node, int] = 0,
        bus: int = 0,
    ):
        """Start the recording.

        Parameters
        ----------
        timetag : float, by default 0 (immediately)
            Time (or time offset when <1e6) to start
        duration : float, optional
            Length of the recording, by default until stopped.
        node : Union[Node, int], optional
            Node that should be recorded, by default 0
        bus : int, by default 0
            Bus that should be recorded

        Raises
        ------
        RuntimeError
            When trying to start a recording unprepared.
        """
        if self._state != RecorderState.PREPARED:
            raise RuntimeError(f"Recorder state must be PREPARED but is {self._state}")
        args = dict(bus=bus, duration=duration or -1, bufnum=self._record_buffer.bufnum)

        with self._server.bundler(timetag=timetag):
            self._record_synth = Synth(
                self._synth_name,
                controls=args,
                server=self._server,
                target=node,
                add_action=AddAction.TO_TAIL,
            )
        self._state = RecorderState.RECORDING

    def pause(self, timetag: float = 0):
        """Pause the recording.

        Parameters
        ----------
        timetag : float, by default 0 (immediately)
            Time (or time offset when <1e6) to pause

        Raises
        ------
        RuntimeError
            When trying to pause if not recording.
        """
        if self._state != RecorderState.RECORDING or self._record_synth is None:
            raise RuntimeError(f"Recorder state must be RECORDING but is {self._state}")
        with self._server.bundler(timetag=timetag):
            self._record_synth.run(False)
        self._state = RecorderState.PAUSED

    def resume(self, timetag: float = 0):
        """Resume the recording

        Parameters
        ----------
        timetag : float, by default 0 (immediately)
            Time (or time offset when <1e6) to resume

        Raises
        ------
        RuntimeError
            When trying to resume if not paused.
        """
        if self._state != RecorderState.PAUSED or self._record_synth is None:
            raise RuntimeError(f"Recorder state must be PAUSED but is {self._state}")
        with self._server.bundler(timetag=timetag):
            self._record_synth.run(True)
        self._state = RecorderState.RECORDING

    def stop(self, timetag: float = 0):
        """Stop the recording.

        Parameters
        ----------
        timetag : float, by default 0 (immediately)
            Time (or time offset when <1e6) to stop

        Raises
        ------
        RuntimeError
            When trying to stop if not started.
        """
        if (
            self._state not in [RecorderState.RECORDING, RecorderState.PAUSED]
            or self._record_synth is None
        ):
            raise RuntimeError(
                f"Recorder state must be RECORDING or PAUSED but is {self._state}"
            )

        with self._server.bundler(timetag=timetag):
            self._record_synth.free()
            self._record_synth = None
            self._record_buffer.close()
        self._state = RecorderState.UNPREPARED

    def __repr__(self) -> str:
        return f"<Recorder [{self._state.value}]>"

    def __del__(self):
        try:
            self.stop()
        except RuntimeError:
            pass
        self._record_buffer.free()
