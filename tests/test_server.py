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
        root_group = self.server.query_all_nodes()
        self.assertEqual(len(root_group.children), self.server.max_logins)
        self.assertIn(self.server.default_group, root_group.children)
        group = Group(server=self.server)
        self.server.sync()
        root_group = self.server.query_all_nodes()
        self.assertIn(group, self.server.default_group.children)
