from unittest import TestCase

from sc3nb.sc_objects.node import Group
from sc3nb.sc_objects.server import SCServer, ServerOptions


class ServerTest(TestCase):
    def setUp(self) -> None:
        self.port = 57777
        options = ServerOptions(udp_port=self.port)
        self.server = SCServer(options=options)
        self.server.boot(with_blip=False)

    def tearDown(self) -> None:
        self.server.quit()

    def test_connection_info(self):
        _, receivers = self.server.connection_info()
        ip_address, port = next(iter(receivers.keys()))
        self.assertEqual(len(receivers), 1)
        self.assertEqual(ip_address, "127.0.0.1")
        self.assertEqual(port, self.port)

    def test_is_local(self):
        self.assertTrue(self.server.is_local)

    def test_sync(self):
        self.assertTrue(self.server.sync(timeout=10))

    def test_node_tree(self):
        root_group = self.server.query_tree()
        self.assertEqual(len(root_group.children), self.server.max_logins)
        self.assertIn(self.server.default_group, root_group.children)
        group = Group(server=self.server)
        self.server.sync()
        root_group = self.server.query_tree()
        self.assertIn(group, self.server.default_group.children)

    def test_multiclient(self):
        options = ServerOptions(udp_port=self.port)
        self.other_server = SCServer(options=options)

        with self.assertRaisesRegex(
            ValueError,
            f"The specified UDP port {self.server.options.udp_port} is already used",
        ):
            self.other_server.boot(timeout=3)
        self.other_server.remote(*self.server.addr)
        self.assertEqual(self.server.addr, self.other_server.addr)
        # check if they share nodes
        group = Group(server=self.other_server)
        root_group = self.server.query_tree()
        matches = [
            child
            for child in root_group.children
            if child.nodeid == self.other_server.default_group.nodeid
        ]
        self.assertEqual(len(matches), 1)
        other_default_group: Group = matches[0]
        self.assertIn(
            group.nodeid, [child.nodeid for child in other_default_group.children]
        )
