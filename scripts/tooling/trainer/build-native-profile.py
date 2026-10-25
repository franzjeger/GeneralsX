#!/usr/bin/env python3
"""Generate a SHA-256-bound trainer profile after checking the native DWARF ABI.

Usage: build-native-profile.py --binary GeneralsXZH --output trainer-profile.json
Requires the unstripped x86-64 Linux build, GDB, nm and readelf. Does not run it.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile

# Keys are the original 1.0.4 trainer's reference addresses, not native addresses.
SYMBOLS = {
    0xC02720: ("ThePlayerList", 0), 0xC04948: ("TheGameLogic", 0),
    0xB6DED0: ("vtable for PlayerList", 16), 0xB8B5F0: ("vtable for Player", 16),
    0xB6DD58: ("vtable for Money", 16), 0xB76658: ("vtable for Object", 16),
    0xB6FCE0: ("vtable for Team", 16), 0xB6FC70: ("vtable for TeamPrototype", 16),
    0xBD7D90: ("vtable for W3DGameLogic", 16), 0xB79D88: ("vtable for LifetimeUpdate", 16),
    0xBCAB38: ("vtable for ProductionUpdate", 16), 0xBCAB10: ("vtable for ProductionEntry", 16),
    0x5A67E0: ("non-virtual thunk to ActiveBody::isIndestructible() const", 0),
    0x5DE850: ("SpecialPowerModule::setReadyFrame(unsigned int)", 0),
    0x5DED30: ("SpecialPowerModule::getReadyFrame() const", 0),
}
LAYOUT = {
    "PlayerList": {"m_local": 24, "m_playerCount": 32, "m_players": 40},
    "Player": {"m_playerTemplate": 8, "m_handicap": 24, "m_playerIndex": 52,
               "m_playerType": 72, "m_money": 80, "m_rankLevel": 960,
               "m_skillPoints": 964, "m_sciencePurchasePoints": 968,
               "m_specialPowerReadyTimerList": 2392},
    "Money": {"m_money": 8, "m_playerIndex": 12},
    "Thing": {"m_template": 8}, "Overridable": {"m_nextOverride": 8},
    "Object": {"m_id": 112, "m_next": 144, "m_disabledMask": 344,
               "m_behaviors": 472, "m_body": 488, "m_team": 632},
    "Team": {"m_proto": 16}, "TeamPrototype": {"m_owningPlayer": 24},
    "ThingTemplate": {"m_kindof": 176},
    "GameLogic": {"m_frame": 144, "m_objList": 1808},
    "Module": {"m_moduleData": 16}, "ObjectModule": {"m_object": 24},
    "ProductionUpdate": {"m_productionQueue": 80, "m_productionCount": 100},
    "ProductionEntry": {"m_type": 8, "m_framesUnderConstruction": 32},
    "ActiveBody": {"m_currentHealth": 52, "m_maxHealth": 60, "m_indestructible": 211},
    "SpecialPowerModule": {"m_availableOnFrame": 48, "m_pausedCount": 52},
    "SpecialPowerModuleData": {"m_specialPowerTemplate": 16, "m_scriptedSpecialPowerOnly": 155},
    "SpecialPowerTemplate": {"m_id": 32, "m_sharedNSync": 325},
    "SpecialPowerReadyTimerType": {"m_templateID": 0, "m_readyFrame": 4},
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    binary = args.binary.resolve()
    binary_data = binary.read_bytes()
    header = binary_data[:20]
    if header[:6] != b"\x7fELF\x02\x01" or int.from_bytes(header[18:20], "little") != 62:
        raise ValueError("Only ELF64 little-endian x86-64 binaries are supported")
    nm = subprocess.check_output(["nm", "-S", "-C", "--defined-only", str(binary)], text=True)
    symbols, sizes = {}, {}
    for line in nm.splitlines():
        parts = line.split(maxsplit=3)
        if len(parts) == 4:
            symbols[parts[3]] = int(parts[0], 16)
            sizes[parts[3]] = int(parts[1], 16)
    addresses = {str(old): symbols[name] + add for old, (name, add) in SYMBOLS.items()}
    sections = subprocess.check_output(["readelf", "-SW", str(binary)], text=True)
    match = re.search(r"\.data\.rel\.ro\s+PROGBITS\s+([\da-f]+)\s+([\da-f]+)\s+([\da-f]+)", sections)
    if not match:
        raise ValueError("Missing vtable section")
    start, file_offset, size = (int(x, 16) for x in match.groups())
    addresses[str(0xB00000)] = start
    addresses[str(0xC00000)] = start + size
    def qword(address):
        if not start <= address <= start + size - 8:
            raise ValueError("Vtable extends outside its ELF section")
        return struct.unpack_from("<Q", binary_data, file_offset + address - start)[0]
    power = symbols["vtable for SpecialPowerModule"] + 16
    for slot, reference in ((52, 0x5DED30), (57, 0x5DE850)):
        if qword(power + slot * 8) != addresses[str(reference)]:
            raise ValueError(f"Unsupported special-power virtual slot {slot}")
    body = symbols["vtable for ActiveBody"]
    valid_body = any(qword(body + index) == (1 << 64) - 40
                     and qword(body + index + 16 + 33 * 8) == addresses[str(0x5A67E0)]
                     for index in range(0, sizes["vtable for ActiveBody"] - (16 + 33 * 8), 8))
    if not valid_body:
        raise ValueError("Unsupported ActiveBody interface virtual layout")
    with tempfile.TemporaryDirectory(prefix="generalsx-trainer-") as temporary:
        directory = Path(temporary)
        result = directory / "layout.json"
        script = directory / "check.py"
        script.write_text("""import gdb, json
expected = """ + repr(LAYOUT) + """
def offset(typ, name):
    for field in typ.fields():
        if field.name == name and hasattr(field, 'bitpos'):
            return field.bitpos // 8
    for field in typ.fields():
        if field.is_base_class:
            found = offset(field.type, name)
            if found is not None:
                return field.bitpos // 8 + found
    return None
def base(typ, name):
    for field in typ.fields():
        if field.is_base_class:
            if field.type.name == name:
                return field.bitpos // 8
            found = base(field.type, name)
            if found is not None:
                return field.bitpos // 8 + found
    return None
actual = {}
for cls, fields in expected.items():
    typ = gdb.lookup_type(cls)
    actual[cls] = {}
    for name, want in fields.items():
        got = offset(typ, name)
        if got != want:
            raise RuntimeError('%s.%s: expected %d, found %s' % (cls, name, want, got))
        actual[cls][name] = got
if base(gdb.lookup_type('ActiveBody'), 'BodyModuleInterface') != 40:
    raise RuntimeError('Unsupported ActiveBody interface offset')
if int(gdb.parse_and_eval('sizeof(((Player*)0)->m_specialPowerReadyTimerList)')) != 24:
    raise RuntimeError('Unsupported shared timer list ABI')
with open(""" + repr(str(result)) + """, 'w') as output:
    json.dump(actual, output, indent=2)
""")
        checked = subprocess.run(["gdb", "-nx", "-batch", str(binary), "-ex", "source " + str(script)],
                                 check=True, capture_output=True, text=True)
        if not result.exists():
            # GDB may return zero after an embedded Python error.
            raise ValueError("Native memory layout did not match the trainer ABI: "
                             + (checked.stdout + checked.stderr)[-4000:])
        layout = json.loads(result.read_text())
    profile = {"schema": 1, "name": "Native Linux graphics", "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
               "addresses": addresses, "verified_layout": layout}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp = args.output.with_suffix(".tmp")
    temp.write_text(json.dumps(profile, indent=2) + "\n")
    temp.replace(args.output)
    print(f"Verified {sum(map(len, layout.values()))} native fields; wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
