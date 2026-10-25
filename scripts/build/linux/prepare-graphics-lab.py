#!/usr/bin/env python3
"""Prepare private A/B runtimes from locally owned retail data and generated art.

Usage: prepare-graphics-lab.py [--lab-dir DIR] [--base-data DIR] [--zh-data DIR]
Only the lab directory is written. Retail archives remain linked and read-only
to this script; map edits and texture overrides live in the enhanced runtime.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct

from PIL import Image

REPO = Path(__file__).resolve().parents[3]
SAND_CLASSES = {"SandLargeType4", "SandType3wavy", "SandType6",
                "SandMediumType11", "SandMediumType9", "SandMediumType5c"}
ROCK_CLASSES = {"RocksType2", "RocksType3blue", "RocksType6", "RocksType7"}


def big_files(path):
    with path.open("rb") as stream:
        header = stream.read(16)
        if header[:4] not in (b"BIGF", b"BIG4"):
            raise ValueError(f"Invalid BIG archive: {path}")
        entries = []
        for _ in range(struct.unpack_from(">I", header, 8)[0]):
            offset, size = struct.unpack(">II", stream.read(8))
            name = bytearray()
            while True:
                char = stream.read(1)
                if char == b"\0":
                    break
                if not char:
                    raise ValueError("Truncated BIG index")
                name += char
            entries.append((name.decode().replace("\\", "/"), offset, size))
        for name, offset, size in entries:
            yield name, offset, size


def extract(archive, names):
    result = {}
    with archive.open("rb") as stream:
        for name, offset, size in big_files(archive):
            if name.lower() in names:
                stream.seek(offset)
                result[name.lower()] = stream.read(size)
    return result


def unpack_map(data):
    if data[:4] == b"CkMp":
        return data
    if data[:4] != b"EAR\0" or data[8:10] != b"\x10\xfb":
        raise ValueError("Expected retail RefPack map")
    expected = int.from_bytes(data[4:8], "little")
    source, pos, output = data[8:], 5, bytearray()
    while True:
        first = source[pos]
        pos += 1
        if first < 0x80:
            second = source[pos]
            pos += 1
            literal, offset, count = first & 3, ((first & 0x60) << 3) + second + 1, ((first & 0x1C) >> 2) + 3
        elif first < 0xC0:
            second, third = source[pos:pos + 2]
            pos += 2
            literal, offset, count = second >> 6, ((second & 0x3F) << 8) + third + 1, (first & 0x3F) + 4
        elif first < 0xE0:
            second, third, fourth = source[pos:pos + 3]
            pos += 3
            literal, offset, count = first & 3, ((first & 0x10) << 12) + (second << 8) + third + 1, ((first & 0xC) << 6) + fourth + 5
        else:
            literal = ((first & 0x1F) << 2) + 4 if first < 0xFC else first & 3
            output += source[pos:pos + literal]
            pos += literal
            if first >= 0xFC:
                break
            continue
        output += source[pos:pos + literal]
        pos += literal
        for _ in range(count):
            output.append(output[-offset])
        if len(output) > expected:
            raise ValueError("RefPack output exceeds declared size")
    if len(output) != expected or output[:4] != b"CkMp":
        raise ValueError("Invalid decompressed map")
    return bytes(output)


def map_chunks(data):
    pos, names = 8, {}
    for _ in range(struct.unpack_from("<I", data, 4)[0]):
        length = data[pos]
        name = data[pos + 1:pos + 1 + length].decode()
        pos += length + 1
        key = struct.unpack_from("<I", data, pos)[0]
        pos += 4
        names[key] = name
    header, chunks = data[:pos], []
    while pos < len(data):
        key, version, length = struct.unpack_from("<IHI", data, pos)
        end = pos + 10 + length
        if end > len(data):
            raise ValueError("Invalid chunk size")
        chunks.append((key, version, data[pos + 10:end]))
        pos = end
    return header, names, chunks


def ascii_string(value):
    raw = value.encode("ascii")
    return struct.pack("<H", len(raw)) + raw


def scene_map(data, enhanced):
    header, names, chunks = map_chunks(data)
    ids = {v: k for k, v in names.items()}

    def obj(name, x, y, properties):
        payload = struct.pack("<4fI", x, y, 0, 0.35, 0) + ascii_string(name)
        payload += struct.pack("<H", len(properties))
        for key, value in properties.items():
            kind = 0 if isinstance(value, bool) else 1 if isinstance(value, int) else 3
            payload += struct.pack("<I", (ids[key] << 8) | kind)
            payload += struct.pack("<B", value) if kind == 0 else struct.pack("<i", value) if kind == 1 else ascii_string(value)
        return struct.pack("<IHI", ids["Object"], 3, len(payload)) + payload

    camera = obj("*Waypoints/Waypoint", 1330, 1270,
                 {"waypointName": "InitialCameraPosition", "waypointID": 9999,
                  "uniqueID": "GraphicsLabCamera", "originalOwner": "teamPlyrCivilian"})
    display_objects = bytearray(camera)
    for i, (name, x, y) in enumerate([
            ("AmericaTankCrusader", 1250, 1190),
            ("AmericaVehicleHumvee", 1320, 1190),
            ("ChinaTankOverlord", 1400, 1190),
            ("AmericaInfantryRanger", 1270, 1240),
            ("AmericaInfantryRanger", 1310, 1240)]):
        display_objects += obj(name, x, y,
                               {"originalOwner": "teamPlyrCivilian", "objectInitialHealth": 100,
                                "objectEnabled": True, "objectPowered": True,
                                "objectRecruitableAI": False, "uniqueID": f"GraphicsLab{i}"})
    result = bytearray(header)
    for key, version, payload in chunks:
        if names[key] == "ObjectsList":
            payload += display_objects
        if names[key] == "GlobalLighting" and enhanced:
            if version != 3 or len(payload) != 872:
                raise ValueError("Unexpected global-lighting layout")
            edited = bytearray(payload)
            struct.pack_into("<I", edited, 0, 2)  # Afternoon.
            for time in range(4):
                for light in range(6):
                    ambient = (0.28, 0.31, 0.35) if light < 2 else (0, 0, 0)
                    diffuse = (0.92, 0.86, 0.75) if light < 2 else (0, 0, 0)
                    struct.pack_into("<9f", edited, 4 + (time * 6 + light) * 36,
                                     *ambient, *diffuse, -0.62, 0.30, -0.72)
            # Stencil shadows multiply by RGB; black would erase surface detail.
            struct.pack_into("<I", edited, 868, 0x7F9FA8B3)
            payload = bytes(edited)
        result += struct.pack("<IHI", key, version, len(payload)) + payload
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-dir", type=Path, default=REPO.parent / "development")
    parser.add_argument("--base-data", type=Path, default=Path.home() / "GeneralsX/Generals")
    parser.add_argument("--zh-data", type=Path, default=Path.home() / "GeneralsX/GeneralsZH")
    args = parser.parse_args()
    lab = args.lab_dir.resolve()
    lab.mkdir(parents=True, exist_ok=True)
    files = extract(args.zh_data / "MapsZH.big", {"maps/tournament desert/tournament desert.map"})
    original = unpack_map(files["maps/tournament desert/tournament desert.map"])
    definitions = extract(args.zh_data / "INIZH.big", {"data/ini/terrain.ini"})["data/ini/terrain.ini"].decode()
    selected = {}
    for name, body in re.findall(r"^Terrain\s+(\S+)\s*\n(.*?)^End", definitions, re.M | re.S):
        if name in SAND_CLASSES | ROCK_CLASSES:
            texture = re.search(r"Texture\s*=\s*(\S+)", body)[1]
            selected[f"art/terrain/{texture}".lower()] = (name, texture)
    stock = extract(args.base_data / "Terrain.big", set(selected))
    stock.update(extract(args.zh_data / "TerrainZH.big", set(selected)))
    manifest = {"map": "Tournament Desert", "textures": []}
    for profile in ("baseline", "enhanced"):
        runtime = lab / "runtime" / profile
        runtime.mkdir(parents=True, exist_ok=True)
        for item in args.zh_data.glob("*.big"):
            target = runtime / item.name
            if not target.exists():
                target.symlink_to(item.resolve())
        for item in (args.zh_data / "Data").iterdir():
            if item.name in ("INI", "Art"):
                continue
            target = runtime / "Data" / item.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.symlink_to(item.resolve(), target_is_directory=item.is_dir())
        dest = runtime / "Maps/DesertLab"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "DesertLab.map").write_bytes(scene_map(original, profile == "enhanced"))
        (dest / "map.ini").write_text("GameData\n  ShroudOn = No\n  FogOfWarOn = No\n  DrawEntireTerrain = Yes\n  CameraHeight = 350\n  MinCameraHeight = 350\n  MaxCameraHeight = 350\n  EnforceMaxCameraHeight = Yes\n  EnableDynamicLOD = No\nEnd\n")
        (runtime / "Data/INI").mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / "GeneralsZH/Data/INI/FXListGeneralsX.ini", runtime / "Data/INI/FXListGeneralsX.ini")
        user = lab / "profiles" / profile / "GeneralsX/GeneralsZH"
        user.mkdir(parents=True, exist_ok=True)
        options = user / "Options.ini"
        if not options.exists():
            shutil.copyfile(Path.home() / ".local/share/GeneralsX/GeneralsZH/Options.ini", options)
        text = options.read_text()
        retail_options = (Path.home() / ".local/share/GeneralsX/GeneralsZH/Options.ini").read_text()
        resolution = re.search(r"^Resolution\s*=\s*(.+)$", retail_options, re.M)
        settings = {"Resolution": resolution[1].strip() if resolution else "1920 1080",
                    "DynamicLOD": "no", "StaticGameLOD": "Custom",
                    "CursorCaptureEnabledInWindowedGame": "no", "CursorCaptureEnabledInWindowedMenu": "no",
                    "ScreenEdgeScrollEnabledInWindowedApp": "no",
                    "AntiAliasing": "4", "UseCloudMap": "no", "TextureReduction": "0",
                    "EnablePostProcessing": "no", "UseShadowVolumes": "yes", "UseShadowDecals": "yes",
                    "AdvancedShadows": "yes", "ShadowsForProps": "yes", "UseShadowVolumesForSkins": "yes",
                    "ExtendedShadowFrustumCulling": "yes", "BridgeShadows": "yes"}
        if profile == "enhanced":
            settings.update({"TextureFilter": "Anisotropic", "AnisotropyLevel": "16"})
        for key, value in settings.items():
            line = f"{key} = {value}"
            if re.search(r"^" + key + r"\s*=", text, re.M):
                text = re.sub(r"^" + key + r"\s*=.*$", line, text, flags=re.M)
            else:
                text += "\n" + line + "\n"
        options.write_text(text)
        if profile == "enhanced":
            for path, (name, texture) in selected.items():
                width, height = struct.unpack_from("<HH", stock[path], 12)
                source = REPO / "assets/graphics-lab" / ("sand.png" if name in SAND_CLASSES else "rock.png")
                dest = runtime / "Art/Terrain" / texture
                dest.parent.mkdir(parents=True, exist_ok=True)
                # Format and atlas sizing only; artwork comes from imagegen.
                Image.open(source).convert("RGB").resize((width * 4, height * 4), Image.Resampling.LANCZOS).save(dest, compression=None)
                manifest["textures"].append({"terrain": name, "file": texture, "original_size": [width, height],
                                             "size": [width * 4, height * 4], "sha256": hashlib.sha256(dest.read_bytes()).hexdigest()})
    (lab / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Prepared {lab}: two profiles, {len(selected)} HD terrain replacements.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
