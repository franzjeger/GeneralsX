"""Check ownership boundaries, capture, pool reuse and immunity restoration."""
import os
import struct
import tempfile
import unittest

from zero_hour_trainer import Game


class InvulnerableTest(unittest.TestCase):
    def setUp(self):
        self.file = tempfile.TemporaryFile()
        self.file.truncate(0xD00000)
        self.game = Game.__new__(Game)
        self.game.fd = self.file.fileno()
        self.game.base = 0
        self.game.invulnerable_original = {}
        self.player = 0x1000
        self.game.player = lambda: (self.player, 2)
        self.objects = []
        self.game.objects = lambda: iter(self.objects)

    def put(self, address, fmt, value):
        os.pwrite(self.game.fd, struct.pack(fmt, value), address)

    def unit(self, obj, owner, kind=0x200, original=0):
        template, team, proto, body = obj + 0x800, obj + 0x1000, obj + 0x1200, obj + 0x1600
        for address, value in [(obj, 0xB76658), (obj + 8, template),
                               (obj + 0x278, team), (team, 0xB6FCE0),
                               (team + 0x10, proto), (proto, 0xB6FC70),
                               (proto + 0x18, owner), (obj + 0x1E8, body),
                               (body, 0xB9D5F0), (0xB9D5F0 + 0x108, 0x5A67E0),
                               (body - 0x10, obj), (template + 0xB0, kind)]:
            self.put(address, "<Q", value)
        self.put(obj + 0x70, "<I", obj)
        self.put(body + 0x0C, "<f", 100)
        self.put(body + 0x14, "<f", 200)
        self.put(body + 0xAB, "<B", original)
        self.objects.append(obj)
        return body + 0xAB, proto

    def test_local_only_excludes_projectiles_and_restores_original_flags(self):
        local, _ = self.unit(0x3000, self.player)
        building, _ = self.unit(0x6000, self.player, kind=0x80)
        ai, _ = self.unit(0x9000, 0x2000)
        projectile, _ = self.unit(0xC000, self.player, kind=0x800000)
        scripted, _ = self.unit(0xF000, self.player, original=1)
        self.assertEqual(self.game.invulnerable(True), 3)
        self.assertEqual([self.game.read(a, "<B") for a in
                          (local, building, ai, projectile, scripted)], [1, 1, 0, 0, 1])
        self.game.invulnerable(False)
        self.assertEqual([self.game.read(a, "<B") for a in
                          (local, building, ai, projectile, scripted)], [0, 0, 0, 0, 1])

    def test_capture_removes_protection_and_new_units_receive_it(self):
        captured, proto = self.unit(0x3000, self.player)
        self.game.invulnerable(True)
        self.put(proto + 0x18, "<Q", 0x2000)
        new, _ = self.unit(0x6000, self.player)
        self.game.invulnerable(True)
        self.assertEqual(self.game.read(captured, "<B"), 0)
        self.assertEqual(self.game.read(new, "<B"), 1)

    def test_recycled_object_is_not_restored(self):
        flag, _ = self.unit(0x3000, self.player)
        self.game.invulnerable(True)
        self.put(0x3000 + 0x70, "<I", 4567)
        self.game.invulnerable(False)
        self.assertEqual(self.game.read(flag, "<B"), 1)

    def test_temporary_tunnel_is_not_protected(self):
        flag, _ = self.unit(0x3000, self.player, kind=0x80)
        array, module = 0x6000, 0x7000
        for address, value in [(0x3000 + 0x1D8, array), (array, module),
                               (module, 0xB79D88), (module + 0x18, 0x3000)]:
            self.put(address, "<Q", value)
        self.assertEqual(self.game.invulnerable(True), 0)
        self.assertEqual(self.game.read(flag, "<B"), 0)

    def test_old_protection_on_temporary_tunnel_is_removed(self):
        flag, _ = self.unit(0x3000, self.player, kind=0x80)
        self.game.invulnerable(True)
        array, module = 0x6000, 0x7000
        for address, value in [(0x3000 + 0x1D8, array), (array, module),
                               (module, 0xB79D88), (module + 0x18, 0x3000)]:
            self.put(address, "<Q", value)
        self.game.invulnerable(True)
        self.assertEqual(self.game.read(flag, "<B"), 0)

    def test_capture_immediately_before_write_is_ignored(self):
        flag, proto = self.unit(0x3000, self.player)
        original = self.game.protection_target
        calls = 0

        def capture(obj, player=None):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.put(proto + 0x18, "<Q", 0x2000)
            return original(obj, player)

        self.game.protection_target = capture
        self.game.invulnerable(True)
        self.assertEqual(self.game.read(flag, "<B"), 0)

    def tearDown(self):
        self.file.close()


if __name__ == "__main__":
    unittest.main()
