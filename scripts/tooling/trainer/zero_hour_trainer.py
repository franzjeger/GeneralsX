#!/usr/bin/env python3
"""Local-player trainer for release 1.0.4 and ABI-verified native Linux builds."""
import argparse
import hashlib
import json
import math
import os
import signal
from pathlib import Path
import struct
import sys
import time

SUPPORTED_SHA256 = "de5334a015cc2372cee3be0ef37a5b5363abd864b4bebf3d6f0ab8c19c2584a5"
ROOT = Path(__file__).resolve().parent
TARGET_MONEY = 9_999_999
TARGET_POINTS = 99
_HASH_CACHE = {}


def executable_hash(path):
    info = path.stat()
    key = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
    if key not in _HASH_CACHE:
        if len(_HASH_CACHE) >= 8:
            _HASH_CACHE.clear()
        _HASH_CACHE[key] = hashlib.sha256(path.read_bytes()).hexdigest()
    return _HASH_CACHE[key]


class TrainerError(Exception):
    pass


class Game:
    addresses = None  # Release addresses are retained for existing installations.

    def rva(self, reference):
        if self.addresses is None:
            return reference
        try:
            return self.addresses[str(reference)]
        except KeyError as exc:
            raise TrainerError("Motorprofilen mangler en kontrollert adresse.") from exc

    def __init__(self, pid):
        self.pid = pid
        self.identity = Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1].split()[19]
        maps = Path(f"/proc/{pid}/maps").read_text().splitlines()
        executable = Path(f"/proc/{pid}/exe")
        info = executable.stat()
        exe_maps = []
        for line in maps:
            parts = line.split()
            device = tuple(int(x, 16) for x in parts[3].split(":"))
            if int(parts[4]) == info.st_ino and device == (os.major(info.st_dev), os.minor(info.st_dev)):
                exe_maps.append(parts)
        if not exe_maps:
            raise TrainerError("Fant ikke Zero Hour-motoren.")
        self.base = min(int(parts[0].split("-", 1)[0], 16) - int(parts[2], 16) for parts in exe_maps)
        digest = executable_hash(executable)
        self.engine_name = "GeneralsX Zero Hour 1.0.4"
        if digest != SUPPORTED_SHA256:
            profile_path = ROOT.parents[2] / "build/graphics-lab/trainer-profile.json"
            try:
                profile = json.loads(profile_path.read_text())
                if profile["schema"] != 1 or profile["binary_sha256"] != digest:
                    raise ValueError("Engine hash mismatch")
                if sum(len(fields) for fields in profile["verified_layout"].values()) < 44:
                    raise ValueError("Incomplete ABI validation")
                self.addresses = profile["addresses"]
                if not all(isinstance(v, int) and 0 < v < 0x10000000 for v in self.addresses.values()):
                    raise ValueError("Invalid relative address")
                self.engine_name = profile["name"]
            except (OSError, ValueError, KeyError, TypeError) as exc:
                raise TrainerError("Denne motorutgaven støttes ikke. Bygg native-profilen på nytt og start spillet igjen.") from exc
        self.fd = os.open(f"/proc/{pid}/mem", os.O_RDWR)
        self.speed_original = {}
        self.production_modules = []
        self.production_scan_time = 0
        self.invulnerable_original = {}

    def owns(self, obj, player):
        if self.read(obj, "<Q") != self.base + self.rva(0xB76658):
            return False
        team = self.read(obj + 0x278, "<Q")
        if not team or self.read(team, "<Q") != self.base + self.rva(0xB6FCE0):
            return False
        prototype = self.read(team + 0x10, "<Q")
        return bool(prototype and self.read(prototype, "<Q") == self.base + self.rva(0xB6FC70)
                    and self.read(prototype + 0x18, "<Q") == player)

    def power_state(self, obj, module, player):
        """Accept the verified SpecialPowerModule layout and its subclasses."""
        if not self.owns(obj, player) or self.read(obj + 0x158, "<Q"):
            return None  # Preserve lack of power and other disabled states.
        vtable = self.read(module, "<Q")
        if not self.base + self.rva(0xB00000) <= vtable < self.base + self.rva(0xC00000):
            return None
        if (self.read(vtable + 57 * 8, "<Q") != self.base + self.rva(0x5DE850)
                or self.read(vtable + 52 * 8, "<Q") != self.base + self.rva(0x5DED30)
                or self.read(module + 0x18, "<Q") != obj):
            return None
        ready, paused = self.read(module + 0x30, "<Ii")
        if paused != 0 or ready == 0xFFFFFFFF:
            return None  # Script/upgrade locks and one-shot powers stay locked.
        data = self.read(module + 0x10, "<Q")
        if not data or self.read(data + 0x9B, "<B") != 0:
            return None  # Script-only powers are not player buttons.
        template = self.read(data + 0x10, "<Q")
        seen = set()
        while template and template not in seen and len(seen) < 32:
            seen.add(template)
            following = self.read(template + 8, "<Q")
            if not following:
                break
            template = following
        else:
            return None
        template_id = self.read(template + 0x20, "<I")
        shared = self.read(template + 0x145, "<B")
        if not 0 < template_id < 4096 or shared not in (0, 1):
            return None
        identity = (obj, self.read(obj + 0x70, "<I"), module, data, template, template_id)
        return identity, ready, shared

    def power_targets(self, player):
        for obj in self.objects():
            try:
                if not self.owns(obj, player):
                    continue
                array = self.read(obj + 0x1D8, "<Q")
                if not array:
                    continue
                for index in range(256):
                    module = self.read(array + index * 8, "<Q")
                    if not module:
                        break
                    state = self.power_state(obj, module, player)
                    if state:
                        yield state
            except (OSError, TrainerError):
                continue

    def shared_power_timers(self, player):
        """Read the local player's std::list with backlink and size checks."""
        sentinel = player + 0x958
        first, last, count = self.read(sentinel, "<3Q")
        if count > 512:
            return []
        node, previous = first, sentinel
        result = []
        seen = set()
        while node != sentinel and len(result) < count and node not in seen:
            seen.add(node)
            following, back, template_id, ready = self.read(node, "<QQII")
            if back != previous or not 0 < template_id < 4096:
                return []
            result.append((node, template_id, ready))
            previous, node = node, following
        if node != sentinel or previous != last or len(result) != count:
            return []
        return result

    def cooldowns(self):
        player, _ = self.player()
        logic = self.read(self.base + self.rva(0xC04948), "<Q")
        if not logic or self.read(logic, "<Q") != self.base + self.rva(0xBD7D90):
            raise TrainerError("Fant ikke banens tidtakere.")
        frame = self.read(logic + 0x90, "<I")
        completed, shared_ids = 0, set()
        for identity, ready, shared in self.power_targets(player):
            try:
                current = self.power_state(identity[0], identity[2], player)
                if self.player()[0] != player or not current or current[0] != identity:
                    continue
                if shared:
                    shared_ids.add(identity[-1])
                elif frame < current[1] < 0xFFFFFFFF:
                    if os.pwrite(self.fd, struct.pack("<I", frame), identity[2] + 0x30) == 4:
                        completed += 1
            except (OSError, TrainerError):
                continue
        for node, template_id, ready in self.shared_power_timers(player):
            if template_id not in shared_ids or not frame < ready < 0xFFFFFFFF:
                continue
            # Revalidate list membership, identity and local player before writing.
            if (self.player()[0] == player
                    and (node, template_id, ready) in self.shared_power_timers(player)):
                if os.pwrite(self.fd, struct.pack("<I", frame), node + 0x14) == 4:
                    completed += 1
        return completed

    def objects(self):
        """Walk the engine's live object list, including newly created units."""
        logic = self.read(self.base + self.rva(0xC04948), "<Q")
        if not logic or self.read(logic, "<Q") != self.base + self.rva(0xBD7D90):
            raise TrainerError("Fant ikke banens objektliste.")
        obj = self.read(logic + 0x710, "<Q")
        seen = set()
        while obj and obj not in seen and len(seen) < 100_000:
            seen.add(obj)
            try:
                if self.read(obj, "<Q") != self.base + self.rva(0xB76658):
                    break
                following = self.read(obj + 0x90, "<Q")
                yield obj
                obj = following
            except (OSError, TrainerError):
                break

    def lifetime_module(self, obj):
        """Temporary objects must be allowed to expire through Object::kill()."""
        array = self.read(obj + 0x1D8, "<Q")
        if array:
            for index in range(256):
                module = self.read(array + index * 8, "<Q")
                if not module:
                    break
                if (self.read(module, "<Q") == self.base + self.rva(0xB79D88)
                        and self.read(module + 0x18, "<Q") == obj):
                    return module
        return None

    def protection_target(self, obj, player=None, include_temporary=False):
        """Validate identity, ownership, kind and ActiveBody's immunity field."""
        if self.read(obj, "<Q") != self.base + self.rva(0xB76658):
            return None
        template = self.read(obj + 8, "<Q")
        final_template = template
        seen = set()
        while final_template and final_template not in seen and len(seen) < 32:
            seen.add(final_template)
            following = self.read(final_template + 8, "<Q")
            if not following:
                break
            final_template = following
        else:
            return None
        # KINDOF_STRUCTURE / INFANTRY / VEHICLE / AIRCRAFT. Excludes missiles,
        # weapon effects and scenery, whose scripted lifetime must still expire.
        if not self.read(final_template + 0xB0, "<Q") & 0x780:
            return None
        if not include_temporary and self.lifetime_module(obj):
            return None
        if player is not None:
            team = self.read(obj + 0x278, "<Q")
            if not team or self.read(team, "<Q") != self.base + self.rva(0xB6FCE0):
                return None
            prototype = self.read(team + 0x10, "<Q")
            if not prototype or self.read(prototype, "<Q") != self.base + self.rva(0xB6FC70):
                return None
            if self.read(prototype + 0x18, "<Q") != player:
                return None
        body = self.read(obj + 0x1E8, "<Q")  # BodyModuleInterface subobject.
        if not body:
            return None
        vtable = self.read(body, "<Q")
        if not self.base + self.rva(0xB00000) <= vtable < self.base + self.rva(0xC00000):
            return None
        # ActiveBody::isIndestructible thunk reads byte +0xAB. Its subclasses
        # share this accessor, while InactiveBody and ImmortalBody are excluded.
        if self.read(vtable + 0x108, "<Q") != self.base + self.rva(0x5A67E0):
            return None
        if self.read(body - 0x10, "<Q") != obj:
            return None
        health = self.read(body + 0x0C, "<f")
        maximum = self.read(body + 0x14, "<f")
        flag = self.read(body + 0xAB, "<B")
        if not (math.isfinite(health) and math.isfinite(maximum)
                and 0 < health <= maximum * 100 and maximum > 0 and flag in (0, 1)):
            return None
        identity = (obj, self.read(obj + 0x70, "<I"), body, template)
        return identity, flag

    def invulnerable(self, enabled):
        player = self.player()[0] if enabled else None
        targets = {}
        if enabled:
            for obj in self.objects():
                try:
                    target = self.protection_target(obj, player)
                    if target:
                        targets[target[0]] = target[1]
                except (OSError, TrainerError):
                    continue
        # Restore protection we added when disabled or when an object changes
        # owner. IDs and body identity prevent writes to recycled pool entries.
        for identity, original in list(self.invulnerable_original.items()):
            if identity in targets:
                continue
            try:
                current = self.protection_target(identity[0], include_temporary=True)
                if current and current[0] == identity:
                    os.pwrite(self.fd, bytes([original]), identity[2] + 0xAB)
            except (OSError, TrainerError):
                pass
            del self.invulnerable_original[identity]
        for identity in targets:
            try:
                if self.player()[0] != player:
                    break
                current = self.protection_target(identity[0], player)
                if not current or current[0] != identity:
                    continue
                self.invulnerable_original.setdefault(identity, current[1])
                if os.pwrite(self.fd, b"\x01", identity[2] + 0xAB) != 1:
                    raise TrainerError("Kunne ikke aktivere beskyttelsen.")
            except (OSError, TrainerError):
                continue
        return len(targets)

    def scan_production(self):
        """Find production modules through validated live objects, across all pools."""
        found = set()
        for obj in self.objects():
            try:
                array = self.read(obj + 0x1D8, "<Q")
                if not array:
                    continue
                for index in range(256):
                    module = self.read(array + index * 8, "<Q")
                    if not module:
                        break
                    if self.read(module, "<Q") == self.base + self.rva(0xBCAB38):
                        found.add(module)
            except (OSError, TrainerError):
                continue
        self.production_modules = sorted(found)
        self.production_scan_time = time.monotonic()

    def research_queue(self, module, player):
        """Only accept a live local-owned producer's current upgrade entry."""
        if self.read(module, "<Q") != self.base + self.rva(0xBCAB38):
            return None
        obj = self.read(module + 0x18, "<Q")
        if not obj or self.read(obj, "<Q") != self.base + self.rva(0xB76658):
            return None
        team = self.read(obj + 0x278, "<Q")
        if not team or self.read(team, "<Q") != self.base + self.rva(0xB6FCE0):
            return None
        prototype = self.read(team + 0x10, "<Q")
        if not prototype or self.read(prototype, "<Q") != self.base + self.rva(0xB6FC70):
            return None
        if self.read(prototype + 0x18, "<Q") != player:
            return None
        queue = self.read(module + 0x50, "<Q")
        count = self.read(module + 0x64, "<I")
        if not queue or not 1 <= count <= 100:
            return None
        if self.read(queue, "<Q") != self.base + self.rva(0xBCAB10):
            return None
        if self.read(queue + 8, "<i") != 2:  # PRODUCTION_UPGRADE, never units.
            return None
        frames = self.read(queue + 0x20, "<i")
        if not 0 <= frames <= 100_000_000:
            return None
        return queue

    def research(self):
        player, _ = self.player()
        if time.monotonic() - self.production_scan_time > 15:
            self.scan_production()
        completed = 0
        for module in self.production_modules:
            try:
                queue = self.research_queue(module, player)
                if queue is None or self.read(queue + 0x20, "<i") >= 100_000_000:
                    continue
                # Recheck ownership and queue identity immediately before writing.
                if self.player()[0] != player or self.research_queue(module, player) != queue:
                    continue
                data = struct.pack("<i", 100_000_000)
                if os.pwrite(self.fd, data, queue + 0x20) == len(data):
                    completed += 1
            except (OSError, TrainerError):
                continue  # Destroyed/captured buildings may disappear between ticks.
        return completed

    @classmethod
    def find(cls):
        candidates = []
        for p in Path("/proc").iterdir():
            if not p.name.isdigit():
                continue
            try:
                argv = (p / "cmdline").read_bytes().split(b"\0")
                if argv and Path(os.fsdecode(argv[0])).name == "GeneralsXZH":
                    candidates.append(int(p.name))
            except (OSError, ProcessLookupError):
                continue
        if not candidates:
            raise TrainerError("Start Zero Hour og last inn en bane.")
        if len(candidates) != 1:
            raise TrainerError("Ha bare ett Zero Hour-vindu åpent.")
        return cls(candidates[0])

    def close(self):
        if self.fd is not None:
            try:
                self.invulnerable(False)
                self.speed(False)
            except (OSError, TrainerError):
                pass
            os.close(self.fd)
            self.fd = None

    def read(self, address, fmt):
        size = struct.calcsize(fmt)
        data = os.pread(self.fd, size, address)
        if len(data) != size:
            raise TrainerError("Banen ble endret. Koble til på nytt.")
        values = struct.unpack(fmt, data)
        return values[0] if len(values) == 1 else values

    def player(self):
        identity = Path(f"/proc/{self.pid}/stat").read_text().split(") ", 1)[1].split()[19]
        if identity != self.identity:
            raise TrainerError("Spillet er startet på nytt.")
        player_list = self.read(self.base + self.rva(0xC02720), "<Q")
        if not player_list or self.read(player_list, "<Q") != self.base + self.rva(0xB6DED0):
            raise TrainerError("Venter på at spillet skal bli klart.")
        local = self.read(player_list + 24, "<Q")
        count = self.read(player_list + 32, "<i")
        if not local or not 1 <= count <= 16:
            raise TrainerError("Last inn en bane først.")
        players = self.read(player_list + 40, "<16Q")
        if local not in players or self.read(local, "<Q") != self.base + self.rva(0xB8B5F0):
            raise TrainerError("Fant ikke den lokale spilleren.")
        index = self.read(local + 0x34, "<i")
        controller = self.read(local + 0x48, "<i")
        if index == 0 or controller != 0 or not 0 <= index < 16 or players[index] != local:
            raise TrainerError("Last inn en bane med en menneskelig spiller.")
        if self.read(local + 0x50, "<Q") != self.base + self.rva(0xB6DD58):
            raise TrainerError("Spillerdata stemmer ikke med denne utgaven.")
        if self.read(local + 0x5C, "<i") != index:
            raise TrainerError("Spillerens pengekonto kunne ikke bekreftes.")
        rank, xp, points = self.read(local + 0x3C0, "<iii")
        speed = self.read(local + 0x20, "<ff")
        if not 1 <= rank <= 5 or not 0 <= points <= 1_000_000:
            raise TrainerError("Uventede spillerdata. Ingen endringer gjort.")
        if not all(math.isfinite(x) and 0.00001 <= x <= 1000 for x in speed):
            raise TrainerError("Uventet produksjonstid. Ingen endringer gjort.")
        return local, index

    def status(self):
        player, index = self.player()
        rank, xp, points = self.read(player + 0x3C0, "<iii")
        return {"pid": self.pid, "engine": self.engine_name, "player_index": index,
                "money": self.read(player + 0x58, "<I"), "rank": rank,
                "points": points, "build_factors": self.read(player + 0x20, "<ff")}

    def write_player(self, offset, fmt, value):
        player, _ = self.player()
        data = struct.pack(fmt, value)
        if os.pwrite(self.fd, data, player + offset) != len(data):
            raise TrainerError("Kunne ikke skrive hele verdien.")

    def money(self, amount=TARGET_MONEY):
        if not 0 <= amount <= TARGET_MONEY:
            raise TrainerError("Ugyldig pengebeløp.")
        self.write_player(0x58, "<I", amount)

    def points(self, amount=TARGET_POINTS):
        if not 0 <= amount <= TARGET_POINTS:
            raise TrainerError("Ugyldig antall generalpoeng.")
        self.write_player(0x3C8, "<i", amount)

    def speed(self, enabled):
        player, _ = self.player()
        key = (self.pid, player, self.read(player + 8, "<Q"))
        if enabled:
            if key not in self.speed_original:
                self.speed_original[key] = self.read(player + 0x20, "<ff")
            values = tuple(x / 20 for x in self.speed_original[key])
        else:
            values = self.speed_original.pop(key, None)
            if values is None:
                return
        self.write_player(0x20, "<f", values[0])
        self.write_player(0x24, "<f", values[1])


def gui(activate_all=False, pid=None):
    import gi
    gi.require_version("Gtk", "4.0")
    from gi.repository import Gtk, GLib

    class App(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="no.frank.ZeroHourTrainer")
            self.game = None
            self.last_error = ""

        def do_activate(self):
            if self.get_active_window():
                self.get_active_window().present()
                return
            win = Gtk.ApplicationWindow(application=self, title="Zero Hour Trainer")
            win.set_default_size(430, 430)
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
            for side in ("top", "bottom", "start", "end"):
                getattr(box, f"set_margin_{side}")(22)
            win.set_child(box)
            title = Gtk.Label(label="Zero Hour Trainer", xalign=0)
            title.add_css_class("title-2")
            box.append(title)
            self.status_label = Gtk.Label(label="Kobler til spillet …", xalign=0, wrap=True)
            box.append(self.status_label)
            self.cash = Gtk.CheckButton(label="Hold penger på 9 999 999")
            self.science = Gtk.CheckButton(label="Hold generalpoeng på 99")
            self.fast = Gtk.CheckButton(label="20× raskere enheter og bygninger")
            self.instant_research = Gtk.CheckButton(label="Insta research")
            self.god_mode = Gtk.CheckButton(label="Udødelige enheter og bygninger (bare dine)")
            self.instant_cooldowns = Gtk.CheckButton(label="Instant cooldowns (evner og supervåpen)")
            self.fast.connect("toggled", self.fast_toggled)
            self.god_mode.connect("toggled", self.protection_toggled)
            for check in self.cheats():
                box.append(check)
            activate = Gtk.Button(label="Aktiver alle")
            activate.add_css_class("suggested-action")
            activate.connect("clicked", lambda *_: self.set_all(True))
            box.append(activate)
            stop = Gtk.Button(label="Slå av juks")
            stop.connect("clicked", lambda *_: self.set_all(False))
            box.append(stop)
            note = Gtk.Label(label="Start spillet på vanlig måte, og last inn en bane.\n"
                            "Lukk og åpne generalmenyen for å oppdatere poengvisningen.\n"
                            "Banens låste generalevner forblir låst.", xalign=0, wrap=True)
            note.add_css_class("dim-label")
            box.append(note)
            win.connect("close-request", self.closing)
            GLib.timeout_add(400, self.tick)
            self.tick()
            if activate_all:
                self.set_all(True)
            win.present()

        def cheats(self):
            return (self.cash, self.science, self.fast, self.instant_research,
                    self.god_mode, self.instant_cooldowns)

        def set_all(self, enabled):
            for check in self.cheats():
                check.set_active(enabled)
            self.tick()

        def fast_toggled(self, *_):
            if self.game and not self.fast.get_active():
                try:
                    self.game.speed(False)
                except (OSError, TrainerError):
                    pass

        def protection_toggled(self, *_):
            if self.game and not self.god_mode.get_active():
                try:
                    self.game.invulnerable(False)
                except (OSError, TrainerError):
                    pass

        def tick(self):
            try:
                if self.game is None:
                    self.game = Game(pid) if pid is not None else Game.find()
                if self.cash.get_active():
                    self.game.money()
                if self.science.get_active():
                    self.game.points()
                if self.fast.get_active():
                    self.game.speed(True)
                if self.instant_research.get_active():
                    self.game.research()
                if self.god_mode.get_active():
                    protected = self.game.invulnerable(True)
                if self.instant_cooldowns.get_active():
                    self.game.cooldowns()
                s = self.game.status()
                self.status_label.set_text(f"{s['engine']}\nTilkoblet spiller {s['player_index']} · rang {s['rank']}\n"
                                           f"Penger: {s['money']:,}   Generalpoeng: {s['points']}".replace(",", " ")
                                           + (f"\nBeskyttede enheter/bygninger: {protected}"
                                              if self.god_mode.get_active() else ""))
            except (OSError, TrainerError) as exc:
                self.status_label.set_text(str(exc))
                if self.game:
                    self.game.close()
                    self.game = None
            return True

        def closing(self, *_):
            self.set_all(False)
            if self.game:
                self.game.close()
                self.game = None
            return False

    app = App()
    def stop_signal(*_):
        app.closing()
        app.quit()
        return False
    for signum in (signal.SIGTERM, signal.SIGINT):
        GLib.unix_signal_add(GLib.PRIORITY_DEFAULT, signum, stop_signal)
    return app.run([])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--money", type=int)
    parser.add_argument("--points", type=int)
    parser.add_argument("--speed-check", action="store_true", help="Apply and restore the build modifier")
    parser.add_argument("--research-once", action="store_true", help="Complete current local research queues")
    parser.add_argument("--activate-all", action="store_true", help="Open the window with all cheats enabled")
    parser.add_argument("--pid", type=int, help="Select an explicit process for a separate local test session")
    args = parser.parse_args()
    if not (args.status or args.money is not None or args.points is not None or args.speed_check or args.research_once):
        return gui(args.activate_all, args.pid)
    game = Game(args.pid) if args.pid is not None else Game.find()
    try:
        before = game.status()
        if args.money is not None:
            game.money(args.money)
        if args.points is not None:
            game.points(args.points)
        if args.research_once:
            print(json.dumps({"research_completed": game.research()}))
        if args.speed_check:
            game.speed(True)
            print(json.dumps({"fast": game.status()}, ensure_ascii=False))
            game.speed(False)
        print(json.dumps({"before": before, "after": game.status()}, ensure_ascii=False))
    finally:
        game.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (TrainerError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
