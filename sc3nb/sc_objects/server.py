"""Module for managing Server related stuff."""
import warnings

from collections import namedtuple
from typing import Optional

import sc3nb.resources as resources
from sc3nb.process_handling import Process, ProcessTimeout, ALLOWED_PARENTS
from sc3nb.osc.osc_communication import (build_message,
                                         OscCommunication,
                                         SCSYNTH_DEFAULT_PORT)

from sc3nb.sc_objects.node import Group
from sc3nb.sc_objects.synthdef import SynthDef

import sc3nb

SC3NB_SERVER_CLIENT_ID = 1

ServerStatus = namedtuple('ServerStatus',
                          ["num_ugens", "num_synths", "num_groups", "num_synthdefs",
                           "avg_cpu", "peak_cpu", "nominal_sr", "actual_sr"])

ServerVersion = namedtuple('ServerVersion',
                           ["name", "major_version", "minor_version", "patch_version",
                            "git_branch", "commit"])

class Recording():

    def __init__(self, path="record.wav", nr_channels=2,
                 rec_header="wav", rec_format="int16", bufsize=65536, server=None):
        """Prepare a recording.

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
            server used for recording, by default None
            if None it will use sc3nb.SC.default.server
        """
        self.server = server or sc3nb.SC.default.server
        # prepare buffer
        self.record_buffer = sc3nb.Buffer(server=self.server)
        self.record_buffer.alloc(bufsize, channels=nr_channels)
        self.record_buffer.write(path, rec_header, rec_format, 0, 0, True)
        rec_id = self.record_buffer.bufnum

        self.synth_def = SynthDef(f"sc3nb_recording_{rec_id}",
        r"""{ |in, bufnum, duration|
			var tick = Impulse.kr(1);
			var timer = PulseCount.kr(tick) - 1;
			var doneAction = if(duration <= 0, 0, 2);
			Line.kr(0, 0, duration, doneAction:doneAction);
			SendReply.kr(tick, '/recordingDuration', timer, ^rec_id);
			DiskOut.ar(bufnum, In.ar(in, ^nr_channels))
		}""")
        self.synth_name = self.synth_def.add()
        self.record_synth = None


    def start(self, timestamp=0, duration=None, node=None, bus=0):
        # The Node to record immediately after. By default, this is the default group
        if self.record_synth:
            raise RuntimeError("Recording already used.")
        elif not self.record_synth:
            if node is None:
                node = self.server.default_group
            args = dict(bus=bus,
                        duration=duration if duration else -1,
                        bufnum=self.record_buffer.bufnum)
            with self.server.bundler(timestamp=timestamp):
                self.record_synth = sc3nb.Synth(self.synth_name, args=args, server=self.server,
                                                target=node, add_action=sc3nb.AddAction.TO_TAIL)
        else:
            warnings.warn("Recording already started.")

    def pause(self, timestamp=0):
        if self.record_synth:
            with self.server.bundler(timestamp=timestamp):
                self.record_synth.run(False)
        else:
            warnings.warn("You must start the Recording before pausing.")

    def resume(self, timestamp=0):
        if self.record_synth:
            with self.server.bundler(timestamp=timestamp):
                self.record_synth.run(True)
        else:
            warnings.warn("You must start the Recording before resuming.")

    def stop(self, timestamp=0):
        if self.record_synth:
            with self.server.bundler(timestamp=timestamp):
                self.record_synth.free()
                self.record_buffer.close()
        else:
            warnings.warn("You must start the Recording before stopping.")

    def __del__(self):
        self.synth_def.free()
        self.record_buffer.free()
        if self.record_synth:
            self.record_synth.free()


class ServerOptions():
    def __init__(self,
                 udp_port: int = SCSYNTH_DEFAULT_PORT,
                 max_logins: int = 15,
                 num_input_bus: int = 2,
                 num_output_bus: int = 2,
                 num_audio_bus: int = 1024,
                 publish_rendezvous: bool = False,
                 block_size: Optional[int] = None,
                 hardware_buffer_size: Optional[int] = None,
                 hardware_sample_size: Optional[int] = None,
                 hardware_input_device: Optional[str] = None,
                 hardware_output_device: Optional[str] = None,
                 other_options: Optional[list] = None):
        # arguments as sequence as wanted by subprocess.Popen
        self.args = []

        # UDP port
        self.udp_port = udp_port
        self.args += ["-u", f"{self.udp_port}"]

        # max logins
        if 3 <= max_logins <= 32:
            self.max_logins = max_logins
        else:
            # max_logins must be between 3 (sc3nb, sclang (sc3nb), sclang (scide)) and 32
            # see https://scsynth.org/t/how-do-i-connect-sclang-to-an-already-running-server/2498/6
            raise ValueError("max logins must be between 3 and 32")
        self.args += ["-l", f"{self.max_logins}"]

        # audio bus options
        self.num_input_bus = num_input_bus
        self.args += ["-i", f"{self.num_input_bus}"]
        self.num_output_bus = num_output_bus
        self.args += ["-o", f"{self.num_output_bus}"]
        if num_audio_bus < num_input_bus + num_output_bus:
            raise ValueError(f"You need at least {num_input_bus + num_output_bus} audio buses")
        self.num_audio_bus = num_audio_bus
        self.args += ["-a", f"{self.num_audio_bus}"]

        # publish to Rendezvous
        self.publish_rendezvous = 1 if publish_rendezvous else 0
        self.args += ["-R", f"{self.publish_rendezvous}"]

        if block_size is not None:
            self.block_size = block_size
            self.args += ["-z", f"{self.block_size}"]

        if hardware_buffer_size is not None:
            self.hardware_buffer_size = hardware_buffer_size
            self.args += ["-Z", f"{self.hardware_buffer_size}"]

        if hardware_sample_size is not None:
            self.hardware_sample_size = hardware_sample_size
            self.args += ["-S", f"{self.hardware_sample_size}"]

        # hardware in/out device
        if not hardware_input_device:
            self.hardware_input_device = ""
        else:
            self.hardware_input_device = hardware_input_device
        if not hardware_output_device:
            self.hardware_output_device = ""
        else:
            self.hardware_output_device = hardware_output_device
        if hardware_input_device or hardware_output_device:
            self.args += ["-H",
                          f"{self.hardware_input_device} {self.hardware_output_device}".strip()]

        # misc. options
        self.other_options = other_options
        if self.other_options:
            self.args += self.other_options

    def first_private_bus(self):
        # after the outs and ins
        return self.num_output_bus + self.num_input_bus


class SCServer():


    def __init__(self, server_options: ServerOptions = None):
        # process
        if server_options is None:
            self.server_options = ServerOptions()
        else:
            self.server_options = server_options

        self.osc = OscCommunication()
        self.msg = self.osc.msg
        self.bundler = self.osc.bundler
        self.send = self.osc.send
        self.sync = self.osc.sync

        self._default_group = None
        self._is_local = None

        # counter for nextNodeID
        self._num_node_ids = 0
        self._num_buffer_ids = 0

        self._address = None # "127.0.0.1"
        self._port = None

        self.process = None

        self.client_id = SC3NB_SERVER_CLIENT_ID
        self._server_running = False
        self._has_booted = False

    def boot(self, scsynth_path=None, timeout=3, console_logging=True, with_blip=True, allowed_parents=ALLOWED_PARENTS):
        if self._has_booted:
            warnings.warn("already booted")
            return
        print('Booting SuperCollider Server...')
        self._is_local = True
        self._address = "127.0.0.1"
        self._port = self.server_options.udp_port
        self.process = Process(executable='scsynth',
                               args=self.server_options.args,
                               exec_path=scsynth_path,
                               console_logging=console_logging,
                               allowed_parents=allowed_parents)
        try:
            self.process.read(expect="SuperCollider 3 server ready.", timeout=timeout)
        except ProcessTimeout as process_timeout:
            if "Exception in World_OpenUDP" in process_timeout.output:
                # ToDo check if string is correct in Win/Linux
                self.process.kill()
                self.process = None
                print("SuperCollider Server port already used.")
                if self.server_options.udp_port != SCSYNTH_DEFAULT_PORT:
                    raise ValueError(
                        f"The specified UDP port {self.server_options.udp_port} is already used")
                else:
                    print("Trying to connect.")
                    self.remote(self._address, self._port, with_blip=with_blip)
            else:
                print("Failed booting SuperCollider Server.")
                raise process_timeout
        else:
            self.init(with_blip)
            self._has_booted = True

    def init(self, with_blip=True):
        # notify the supercollider server about us
        self.osc.set_scsynth(scsynth_ip=self._address, scsynth_port=self._port)
        
        self.notify(timeout=10)

        # load synthdefs of sc3nb
        directory = resources.__file__[:-len("__init__.py")]
        self.load_directory(directory)

        # create default group
        self._default_group = Group(nodeid=1, target=0, server=self)

        self.sync(timeout=10)  # ToDo: fix temporary test
        if with_blip:
            self.blip()

        self._has_booted = True
        print('Done.')

    def blip(self):
        with self.bundler(0.1) as bundler:
            bundler.add(0.1, "/s_new", ["s1", -1, 0, 1, "freq", 500, "dur", 0.1, "num", 1])
            bundler.add(0.3, "/s_new", ["s2", -1, 0, 1, "freq", 1000, "amp", 0.05, "num", 2])
            bundler.add(0.4, "/n_free", [-1])

    def remote(self, address, port, with_blip=True):
        self._is_local = False
        self._address = address
        self._port = port
        self.init(with_blip=with_blip)
        self._has_booted = True

    def reboot(self):
        if not self.is_local:
            raise NotImplementedError("Can't reboot a remote Server")
        self.quit()
        self.boot()

    def ping(self):
        raise NotImplementedError

    # messages
    def quit(self):
        try:
            self.send(build_message("/quit"))
        except ChildProcessError:
            pass  # sending failed. scscynth maybe dead already.
        finally:
            self.osc.exit()
            if self._is_local:
                self.process.kill()

    def send_synthdef(self, synthdef_bytes):
        msg = build_message("/d_recv", synthdef_bytes)
        return self.send(msg)

    def load_synthdef(self, synthdef_path):
        msg = build_message("/d_load", synthdef_path)
        return self.send(msg)

    def load_directory(self, directory, completion_msg=None):
        msg = build_message("/d_loadDir", [directory])
        return self.send(msg)

    def notify(self, receive_notifications=True, timeout=5):
        flag = 1 if receive_notifications else 0
        msg = build_message("/notify", [flag, self.client_id])  # flag, clientID
        return self.send(msg, timeout=timeout)

    def free_all(self, root=False):
        nodeid = 0 if root else self._default_group.nodeid
        msg = build_message("/g_freeAll", nodeid)
        self.send(msg)
        msg = build_message("/clearSched")
        self.send(msg)
		#self.initTree()
        # send DefaultGroups
        self._default_group.new()
        self.sync()
        # tree.value(this)
        # sync
        # ServerTree.run(this)
        # sync
        # AppClock?

    def next_node_id(self):
        self._num_node_ids += 1
        node_id = self._num_node_ids + 10000
        return node_id

    def next_buffer_id(self):
        self._num_buffer_ids += 1
        node_id = self._num_buffer_ids + 100
        return node_id

    @property
    def default_group(self):
        return self._default_group

    @property
    def input_bus(self):
        raise NotImplementedError

    @property
    def output_bus(self):
        raise NotImplementedError

    # Volume Class in Supercollider. Controls Filter Synth
    @property
    def volume(self):
        raise NotImplementedError

    @volume.setter
    def volume(self):
        raise NotImplementedError

    def mute(self):
        raise NotImplementedError

    def unmute(self):
        raise NotImplementedError

    # Information and debugging
    def version(self):
        msg = build_message("/version")
        return ServerVersion._make(self.send(msg))

    def status(self):
        msg = build_message("/status")
        return ServerStatus._make(self.send(msg)[1:])

    def dump_osc(self, level=1):
        msg = build_message("/dumpOSC", [level])
        self.send(msg)

    def dump_tree(self, post_controls=True):
        msg = build_message("/g_dumpTree", [0, 1 if post_controls else 0])
        return self.send(msg)

    def query_all_nodes(self, flag=0):
        msg = build_message("/g_queryTree", [0, flag])
        return self.send(msg)

    @property
    def peak_cpu(self):
        return self.status().peak_cpu

    @property
    def avg_cpu(self):
        return self.status().peak_cpu
    
    @property
    def latency(self):
        raise NotImplementedError

    @latency.setter
    def latency(self):
        raise NotImplementedError

    @property
    def sample_rate(self):
        return self.status().nominal_sr

    @property
    def actual_sample_rate(self):
        return self.status().actual_sr

    @property
    def num_synths(self):
        return self.status().num_synths

    @property
    def num_groups(self):
        return self.status().num_groups

    @property
    def num_ugens(self):
        return self.status().num_ugens

    @property
    def num_synthdefs(self):
        return self.status().num_synthdefs

    @property
    def addr(self):
        return (self._address, self._port)

    @property
    def has_booted(self):
        return self._has_booted

    @property
    def server_running(self):
        return self._server_running

    @property
    def unresponsive(self):
        raise NotImplementedError

    @property
    def is_local(self):
        return self._is_local

    @property
    def pid(self):
        if self.is_local:
            return self.process.popen.pid
        else:
            warnings.warn("Server is not local or not booted.")
