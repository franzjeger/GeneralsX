"""Verify local cooldowns, shared timers and locks across ownership changes."""
import os
import struct
import tempfile
import unittest

from zero_hour_trainer import Game


class CooldownTest(unittest.TestCase):
    def setUp(self):
        self.file = tempfile.TemporaryFile()
        self.file.truncate(0xD00000)
        self.game = Game.__new__(Game)
        self.game.fd = self.file.fileno()
        self.game.base = 0
        self.player = 0x1000
        self.game.player = lambda: (self.player, 2)
        self.objects = []
        self.game.objects = lambda: iter(self.objects)
        self.put(0xC04948, "<Q", 0x2000)
        self.put(0x2000, "<Q", 0xBD7D90)
        self.put(0x2090, "<I", 100)
        self.timers(self.player, [])

    def put(self, address, fmt, value):
        values = value if isinstance(value, tuple) else (value,)
        os.pwrite(self.game.fd, struct.pack(fmt, *values), address)

    def power(self, obj, owner, shared=0, paused=0, ready=900, scripted=0):
        team, proto, array, module, data, template = [obj + x for x in
                                                   (0x400, 0x600, 0x800, 0xA00, 0xC00, 0xE00)]
        for address, value in [(obj, 0xB76658), (obj + 0x278, team),
                               (team, 0xB6FCE0), (team + 0x10, proto),
                               (proto, 0xB6FC70), (proto + 0x18, owner),
                               (obj + 0x1D8, array), (array, module),
                               (module, 0xBB4DA8), (module + 0x18, obj),
                               (module + 0x10, data), (data + 0x10, template),
                               (0xBB4DA8 + 57 * 8, 0x5DE850),
                               (0xBB4DA8 + 52 * 8, 0x5DED30)]:
            self.put(address, "<Q", value)
        self.put(obj + 0x70, "<I", obj)
        self.put(module + 0x30, "<Ii", (ready, paused))
        self.put(data + 0x9B, "<B", scripted)
        self.put(template + 0x20, "<I", obj // 0x1000)
        self.put(template + 0x145, "<B", shared)
        self.objects.append(obj)
        return module, proto

    def timers(self, player, entries):
        sentinel = player + 0x958
        nodes = [player + 0x20000 + i * 0x100 for i in range(len(entries))]
        self.put(sentinel, "<QQQ", (nodes[0] if nodes else sentinel,
                                   nodes[-1] if nodes else sentinel, len(nodes)))
        for i, (template_id, ready) in enumerate(entries):
            self.put(nodes[i], "<QQII", (nodes[i + 1] if i + 1 < len(nodes) else sentinel,
                                        nodes[i - 1] if i else sentinel, template_id, ready))
        return nodes

    def test_only_local_power_finishes(self):
        local, _ = self.power(0x4000, self.player)
        ai, _ = self.power(0x6000, 0x3000)
        self.assertEqual(self.game.cooldowns(), 1)
        self.assertEqual(self.game.read(local + 0x30, "<I"), 100)
        self.assertEqual(self.game.read(ai + 0x30, "<I"), 900)

    def test_only_matching_local_shared_timer_finishes(self):
        self.power(0x4000, self.player, shared=1)
        local, unmatched = self.timers(self.player, [(4, 900), (5, 900)])
        foreign = self.timers(0x3000, [(4, 900)])[0]
        self.assertEqual(self.game.cooldowns(), 1)
        self.assertEqual(self.game.read(local + 0x14, "<I"), 100)
        self.assertEqual(self.game.read(unmatched + 0x14, "<I"), 900)
        self.assertEqual(self.game.read(foreign + 0x14, "<I"), 900)

    def test_paused_one_shot_scripted_and_disabled_powers_stay_unchanged(self):
        modules = [self.power(0x4000, self.player, paused=1)[0],
                   self.power(0x6000, self.player, ready=0xFFFFFFFF)[0],
                   self.power(0x8000, self.player, scripted=1)[0],
                   self.power(0xA000, self.player)[0]]
        self.put(0xA158, "<Q", 1)
        self.assertEqual(self.game.cooldowns(), 0)
        self.assertEqual([self.game.read(m + 0x30, "<I") for m in modules],
                         [900, 0xFFFFFFFF, 900, 900])

    def test_capture_before_write_is_ignored(self):
        module, proto = self.power(0x4000, self.player)
        original = self.game.power_state
        calls = 0

        def capture(obj, mod, player):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.put(proto + 0x18, "<Q", 0x3000)
            return original(obj, mod, player)

        self.game.power_state = capture
        self.assertEqual(self.game.cooldowns(), 0)
        self.assertEqual(self.game.read(module + 0x30, "<I"), 900)

    def test_broken_shared_list_is_not_written(self):
        self.power(0x4000, self.player, shared=1)
        node = self.timers(self.player, [(4, 900)])[0]
        self.put(node + 8, "<Q", 0)
        self.assertEqual(self.game.cooldowns(), 0)
        self.assertEqual(self.game.read(node + 0x14, "<I"), 900)

    def tearDown(self):
        self.file.close()


if __name__ == "__main__":
    unittest.main()
