"""Verify research completion does not touch AI, unit queues, or captured labs."""
import os
import struct
import tempfile
import time
import unittest

from zero_hour_trainer import Game


class ResearchTest(unittest.TestCase):
    def setUp(self):
        self.file = tempfile.TemporaryFile()
        self.file.truncate(0x20000)
        self.game = Game.__new__(Game)
        self.game.fd = self.file.fileno()
        self.game.base = 0x100000
        self.player = 0x1000
        self.game.player = lambda: (self.player, 4)
        self.game.production_scan_time = time.monotonic()
        self.game.production_modules = []

    def put(self, address, fmt, value):
        os.pwrite(self.game.fd, struct.pack(fmt, value), address)

    def producer(self, module, owner, kind):
        obj, team, proto, queue = module + 0x200, module + 0x600, module + 0x800, module + 0xA00
        for address, value in [(module, self.game.base + 0xBCAB38),
                               (module + 0x18, obj), (obj, self.game.base + 0xB76658),
                               (obj + 0x278, team), (team, self.game.base + 0xB6FCE0),
                               (team + 0x10, proto), (proto, self.game.base + 0xB6FC70),
                               (proto + 0x18, owner), (module + 0x50, queue),
                               (queue, self.game.base + 0xBCAB10)]:
            self.put(address, "<Q", value)
        self.put(module + 0x64, "<I", 1)
        self.put(queue + 8, "<i", kind)
        self.put(queue + 0x20, "<i", 10)
        self.game.production_modules.append(module)
        return queue, proto

    def test_only_local_research_finishes(self):
        local, _ = self.producer(0x3000, self.player, 2)
        ai, _ = self.producer(0x6000, 0x2000, 2)
        unit, _ = self.producer(0x9000, self.player, 1)
        self.assertEqual(self.game.research(), 1)
        self.assertEqual(self.game.read(local + 0x20, "<i"), 100_000_000)
        self.assertEqual(self.game.read(ai + 0x20, "<i"), 10)
        self.assertEqual(self.game.read(unit + 0x20, "<i"), 10)

    def test_capture_between_read_and_write_is_ignored(self):
        queue, proto = self.producer(0x3000, self.player, 2)
        original = self.game.research_queue
        calls = 0

        def change_owner(module, player):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.put(proto + 0x18, "<Q", 0x2000)
            return original(module, player)

        self.game.research_queue = change_owner
        self.assertEqual(self.game.research(), 0)
        self.assertEqual(self.game.read(queue + 0x20, "<i"), 10)

    def tearDown(self):
        self.file.close()


if __name__ == "__main__":
    unittest.main()
