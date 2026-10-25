"""Run ownership/restoration tests with relocated engine symbols, as native builds do."""
import test_cooldowns
import test_invulnerable
import test_research

from zero_hour_trainer import Game

REFERENCES = (0xC02720, 0xC04948, 0xB6DED0, 0xB8B5F0, 0xB6DD58,
              0xB76658, 0xB6FCE0, 0xB6FC70, 0xBD7D90, 0xB79D88,
              0xBCAB38, 0xBCAB10, 0x5A67E0, 0x5DE850, 0x5DED30)
RELOCATED = {str(value): value + 0x18000 for value in REFERENCES}
RELOCATED.update({str(0xB00000): 0xB00000, str(0xC00000): 0xC00000})


class RelocatedMemory:
    def setUp(self):
        self.previous_addresses = Game.addresses
        Game.addresses = RELOCATED
        try:
            super().setUp()
        except Exception:
            Game.addresses = self.previous_addresses
            raise

    def put(self, address, fmt, value):
        def relocate(number):
            if not isinstance(number, int):
                return number
            reference = number - self.game.base
            return self.game.base + RELOCATED[str(reference)] if str(reference) in RELOCATED else number
        address = relocate(address)
        value = tuple(relocate(v) for v in value) if isinstance(value, tuple) else relocate(value)
        super().put(address, fmt, value)

    def tearDown(self):
        try:
            super().tearDown()
        finally:
            Game.addresses = self.previous_addresses


class NativeCooldowns(RelocatedMemory, test_cooldowns.CooldownTest):
    pass


class NativeProtection(RelocatedMemory, test_invulnerable.InvulnerableTest):
    pass


class NativeResearch(RelocatedMemory, test_research.ResearchTest):
    pass
