"""Module for creating SuperCollider OSC files that can be used for non-realtime synthesis

`SuperCollider Guide - Non-Realtime Synthesis <http://doc.sccode.org/Guides/Non-Realtime-Synthesis.html>`_

"""
import os
import subprocess
import warnings
from typing import Dict, List, Optional, Union

from pythonosc.osc_bundle import OscBundle
from pythonosc.osc_bundle_builder import OscBundleBuilder
from pythonosc.parsing import osc_types

from sc3nb.osc.osc_communication import OSCMessage, convert_to_sc3nb_osc
from sc3nb.process_handling import find_executable
from sc3nb.sc_objects.server import ServerOptions

NRT_SERVER_OPTIONS = "-u 57110 -a 1024 -i 2 -o 2 -R 0 -l 1".split(" ")


class Score:
    @classmethod
    def load_file(
        cls, path: Union[str, bytes, os.PathLike]
    ) -> Dict[float, List[OSCMessage]]:
        """Load a OSC file into a dict.

        Parameters
        ----------
        path : Union[str, bytes, os.PathLike]
            Path of the OSC file.

        Returns
        -------
        Dict[float, List[OSCMessage]]
            dict with time tag as keys and lists of OSCMessages as values.
        """
        with open(path, "rb") as file:
            dgram = file.read()
        index = 0
        builder = OscBundleBuilder(0)
        while dgram[index:]:
            size, index = osc_types.get_int(dgram, index)
            builder.add_content(OscBundle(dgram[index : index + size]))
            index += size
        #  TODO rework that times don't get smashed
        warnings.warn(
            "This method currently destroys the time tag if they happend in the past."
        )
        return convert_to_sc3nb_osc(builder.build()).messages()

    @classmethod
    def write_file(
        cls,
        messages: Dict[float, List[OSCMessage]],
        path: Union[str, bytes, os.PathLike],
        tempo: float = 1,
    ):
        """Write this score as binary OSC file for NRT synthesis.

        Parameters
        ----------
        messages : Dict[float, List[OSCMessage]]
            Dict with times as key and lists of OSC messages as values
        path : Union[str, bytes, os.PathLike]
            output path for the binary OSC file
        tempo : float
            Times will be multiplied by 1/tempo
        """
        tempo_factor = tempo / 1
        with open(path, "wb") as file:
            msg = None
            for timetag, msgs in messages.items():
                builder = OscBundleBuilder((timetag * tempo_factor) - 2208988800.0)
                for msg in msgs:
                    builder.add_content(msg.to_pythonosc())
                dgram = builder.build().dgram
                file.write(osc_types.write_int(len(dgram)))
                file.write(dgram)
            if msg and (msg.address != "/c_set" or msg.parameters != [0, 0]):
                warnings.warn(
                    "Missing /c_set [0, 0] at the end of the messages. "
                    "Recording will stop with last timetag"
                )

    @classmethod
    def record_nrt(
        cls,
        messages: Dict[float, List[OSCMessage]],
        osc_path: str,
        out_file: str,
        in_file: Optional[str] = None,
        sample_rate: int = 44100,
        header_format: str = "AIFF",
        sample_format: str = "int16",
        options: Optional[ServerOptions] = None,
    ):
        """Write an OSC file from the messages and wri

        Parameters
        ----------
        messages : Dict[float, List[OSCMessage]]
            Dict with times as key and lists of OSC messages as values.
        osc_path : str
            Path of the binary OSC file.
        out_file : str
            Path of the resulting sound file.
        in_file : Optional[str], optional
            Path of input soundfile, by default None.
        sample_rate : int, optional
            sample rate for synthesis, by default 44100.
        header_format : str, optional
            header format of the output file, by default "AIFF".
        sample_format : str, optional
            sample format of the output file, by default "int16".
        options : Optional[ServerOptions], optional
            instance of server options to specify server options, by default None

        Returns
        -------
        subprocess.CompletedProcess
            Completed scsynth non-realtime process.
        """
        cls.write_file(messages, osc_path)
        in_file = in_file or "_"
        args = [
            find_executable("scsynth"),
            "-N",
            osc_path,
            in_file,
            out_file,
            str(sample_rate),
            header_format,
            sample_format,
        ]
        if options:
            args.extend(options.options)
        completed_process = subprocess.run(
            args=args,
            check=True,
            universal_newlines=True,  # py>=3.7 text=True
            stdout=subprocess.PIPE,  # py>=3.7 capture_output=True
            stderr=subprocess.PIPE,
        )
        print(completed_process.stdout)
        print(completed_process.stderr)
        return completed_process
