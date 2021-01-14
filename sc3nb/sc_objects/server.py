"""Module for managing Server related stuff."""
import warnings

from typing import Optional

import sc3nb.resources as resources
from sc3nb.process_handling import Process, ProcessTimeout
from sc3nb.osc.osc_communication import (build_message, Bundler,
                                         OscCommunication,
                                         SCSYNTH_DEFAULT_PORT)

from sc3nb.sc_objects.node import Group

SC3NB_SERVER_CLIENT_ID = 1

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
        #if osc_args is None:
        #    osc_args = {}
        self.osc = OscCommunication()
        self.msg = self.osc.msg

        self._bundling_bundle = None

        self._default_group = None

        self._is_local = None

        # counter for nextNodeID
        self._num_node_ids = 0
        self._num_buffer_ids = 0

        # recording node
        self._rec_node_id = -1  # i.e. not valid
        self._rec_bufnum = -1

        self._address = None # "127.0.0.1"
        self._port = None

        self.process = None

        self.client_id = SC3NB_SERVER_CLIENT_ID
        self._server_running = False
        self._has_booted = False

    def boot(self, scsynth_path=None, timeout=3, console_logging=True, with_blip=True):
        if self._has_booted:
            warnings.warn("already booted")
            return
        print('Booting SuperCollider Server...')
        self._address = "127.0.0.1"
        self._is_local = True
        self._port = self.server_options.udp_port
        self.process = Process(executable='scsynth',
                               args=self.server_options.args,
                               exec_path=scsynth_path,
                               console_logging=console_logging,
                               allowed_parents=["scide", "ipykernel"])
        try:
            self.process.read(expect="SuperCollider 3 server ready.", timeout=timeout)
        except ProcessTimeout as process_timeout:
            if "Only one usage" in process_timeout.output:
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
        self.notify()

        # load synthdefs of sc3nb
        directory = resources.__file__[:-len("__init__.py")]
        self.load_directory(directory)

        # create default group
        self._default_group = Group(nodeid=1, target=0, server=self)

        self.sync()
        if with_blip:
            self.blip()

        self._has_booted = True
        print('Done.')

    def blip(self):
        with self.bundler(0.1) as bundler:
            bundler.add(0.1, "/s_new", ["s1", -1, 1, 1, "freq", 500, "dur", 0.1, "num", 1])
            bundler.add(0.3, "/s_new", ["s2", -1, 1, 1, "freq", 1000, "amp", 0.05, "num", 2])
            bundler.add(0.4, "/n_free", [-1])

    def remote(self, address, port, with_blip=True):
        self._is_local = False
        self._address = address
        self._port = port
        self.osc.set_scsynth(scsynth_ip=self._address, scsynth_port=self._port)
        self.init(with_blip)
        self._has_booted = True

    def reboot(self):
        if not self.is_local:
            raise NotImplementedError("Can't reboot a remote Server")
        self.quit()
        self.boot()


    def bundler(self, timetag=0, msg_addr=None, msg_args=None, send_on_exit=True):
        """Create a Bundler for this server.

        This allows the user to easly add messages/bundles and send it.

        Parameters
        ----------
        timetag : int
            Time at which bundle content should be executed.
            If timetag < 1e6 it is added to time.time().
        msg_addr : str
            SuperCollider address.
        msg_args : list, optional
            List of arguments to add to message.
             (Default value = None)

        Returns
        -------
        Bundler
            custom pythonosc BundleBuilder with add_msg and send
        """
        return Bundler(timetag, msg_addr, msg_args, server=self, send_on_exit=send_on_exit)

    def send(self, content, sync=True, timeout=5, bundled=False, sclang=False):
        if bundled and self._bundling_bundle:
            self._bundling_bundle.add(content)
            return
        return self.osc.send(content,
                             server_address=(self._address, self._port),
                             sync=sync, timeout=timeout, sclang=sclang)


    def ping(self):
        raise NotImplementedError

    # messages

    def quit(self):
        msg = build_message("/quit")
        try:
            self.send(msg)
        except ChildProcessError:
            pass # TODO warn or log?
        self.osc.exit()
        if self._is_local:
            self.process.kill()

    def sync(self):
        self.osc.sync()

    def send_synthdef(self, directory):
        pass

    def load_directory(self, directory, completion_msg=None):
        msg = build_message("/d_loadDir", [directory])
        return self.send(msg)

    def status(self):
        msg = build_message("/status")
        return self.send(msg)

    def notify(self, receive_notifications=True):
        flag = 1 if receive_notifications else 0
        msg = build_message("/notify", [flag, self.client_id])  # flag, clientID
        return self.send(msg)

    def free_all(self):
        msg = build_message("/g_freeAll", 0)
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

    #@property TODO
    def next_node_id(self):
        self._num_node_ids += 1
        node_id = self._num_node_ids + 10000
        return node_id

    #@property TODO
    def next_buffer_id(self):
        self._num_buffer_ids += 1
        node_id = self._num_buffer_ids + 100
        return node_id

    @property
    def options(self):
        raise NotImplementedError

    @options.setter
    def options(self):
        raise NotImplementedError

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

    def dump_osc(self, level=1):
        msg = build_message("/dumpOSC", [level])
        self.send(msg)

    def query_all_nodes(self, flag=0):
        msg = build_message("/g_queryTree", [0, flag])
        return self.send(msg)

    def dump_tree(self, flag=0):
        msg = build_message("/g_dumpTree", [0, flag])
        return self.send(msg)

    @property
    def peak_cpu(self):
        raise NotImplementedError

    @property
    def avg_cpu(self):
        raise NotImplementedError

    @property
    def latency(self):
        raise NotImplementedError

    @latency.setter
    def latency(self):
        raise NotImplementedError

    @property
    def sample_rate(self):
        raise NotImplementedError

    @property
    def actual_sample_rate(self):
        raise NotImplementedError

    @property
    def num_synths(self):
        raise NotImplementedError

    @property
    def num_groups(self):
        raise NotImplementedError

    @property
    def num_ugens(self):
        raise NotImplementedError

    @property
    def num_synthdefs(self):
        raise NotImplementedError

    @property
    def pid(self):
        if self.is_local:
            return self.process.popen.pid
        else:
            warnings.warn("Server is not local or not booted.")

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
    def remote_controlled(self):
        raise NotImplementedError

    # Message Bundling?
    #  make bundle
    #  bind

    # Recording
    def prepare_for_record(self, onset=0, wavpath="record.wav",
                           bufnum=99, nr_channels=2, rec_header="wav",
                           rec_format="int16"): # TODO -> Recorder/Server?

        """Setup recording via scsynth

        Keyword Arguments:
            onset {int} -- Bundle timetag (default: {0})
            wavpath {str} -- Save file path
                             (default: {"record.wav"})
            bufnum {int} -- Buffer number (default: {99})
            nr_channels {int} -- Number of channels
                                 (default: {2})
            rec_header {str} -- File format
                                (default: {"wav"})
            rec_format {str} -- Recording resolution
                                (default: {"int16"})
        """

        self.rec_bufnum = bufnum
        with self.bundler(onset) as bundle:
            bundle.add(onset, "/b_alloc", [self.rec_bufnum, 65536, nr_channels])
            bundle.add(onset+0.2, "/b_write", [self.rec_bufnum,
                                           wavpath, rec_header, rec_format, 0, 0, 1])
            
    def record(self, onset=0, node_id=2001, nr_channels=2):  # TODO -> Recorder/Server?
        """Start recording

        Keyword Arguments:
            onset {int} -- Bundle timetag (default: {0})
            node_id {int} -- SuperCollider Node id
                             (default: {2001})
        """

        self._rec_node_id = node_id
        if nr_channels == 1:
            synth_name = "record-1ch"
        else:
            synth_name = "record-2ch"
            # action = 1 = addtotail
        self.bundler(onset,
                     "/s_new",
                    [synth_name, self._rec_node_id, 1, 0, "bufnum", self.rec_bufnum]
        ).send()

    def pause_recording(self, onset=0):  # TODO -> Recorder/Server?
        pass

    def stop_recording(self, onset=0):  # TODO -> Recorder/Server?
        """Stop recording

        Keyword Arguments:
            onset {int} -- Bundle timetag (default: {0})
        """
        # TODO do this with a record_buffer of type Buffer 
        self.bundler(onset).add(onset, "/n_free", [self._rec_node_id]).add(
                onset+0.5, "/b_close", [self._rec_bufnum]).add(
                    onset+1, "/b_free", [self._rec_bufnum]).send()
