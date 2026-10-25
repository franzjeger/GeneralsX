#!/usr/bin/env python3
"""Install or restore a data-only texture pack in the normal GeneralsX games.

Usage: install-texture-pack.py [--pack-dir DIR] [--restore]
Writes only declared Art files and five graphics-quality preferences. Preserves
original loose files and settings in the pack directory; never changes engines,
retail BIG archives, maps, saves, or trainer code.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

REPO = Path(__file__).resolve().parents[3]
QUALITY = {"TextureFilter": "Anisotropic", "AnisotropyLevel": "16",
           "AntiAliasing": "4", "TextureReduction": "0", "DynamicLOD": "no"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_state(path, state):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(path)


def preference(text, key):
    match = re.search(r"^" + re.escape(key) + r"\s*=\s*(.*?)\s*$", text, re.M)
    return match[1] if match else None


def set_preference(text, key, value):
    pattern = r"^" + re.escape(key) + r"\s*=.*(?:\n|$)"
    if value is None:
        return re.sub(pattern, "", text, flags=re.M)
    line = f"{key} = {value}\n"
    return re.sub(pattern, line, text, flags=re.M) if re.search(pattern, text, re.M) else text.rstrip() + "\n" + line


def restore(pack, state_path, state):
    # Validate everything before the first mutation. Respect files/preferences
    # the user edited after installation instead of silently removing them.
    for name, entry in state["files"].items():
        target = Path(name)
        if target.exists() and digest(target) != entry["installed_sha256"]:
            raise ValueError(f"File changed after installation; restore manually: {target}")
        if entry["original"] is not None and not (pack / entry["original"]).is_file():
            raise FileNotFoundError(pack / entry["original"])
    for name, keys in state["preferences"].items():
        text = Path(name).read_text()
        for key, entry in keys.items():
            if preference(text, key) != entry["installed"]:
                raise ValueError(f"Preference changed after installation: {name}: {key}")
    for name, entry in state["files"].items():
        target = Path(name)
        if entry["original"] is None:
            target.unlink(missing_ok=True)
        else:
            shutil.copyfile(pack / entry["original"], target)
    for name, keys in state["preferences"].items():
        path = Path(name)
        text = path.read_text()
        for key, entry in keys.items():
            text = set_preference(text, key, entry["original"])
        path.write_text(text)
    state["active"] = False
    save_state(state_path, state)
    print(f"Restored {len(state['files'])} texture files and original texture preferences.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=REPO.parent / "texture-pack")
    parser.add_argument("--restore", action="store_true")
    args = parser.parse_args()
    pack = args.pack_dir.resolve()
    state_path = pack / "install-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {
        "active": False, "files": {}, "preferences": {}}
    if args.restore:
        if not state["active"]:
            print("Texture pack is already inactive.")
            return 0
        restore(pack, state_path, state)
        return 0
    manifest = json.loads((pack / "manifest.json").read_text())
    previously_active = state["active"]
    for entry in manifest["files"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "Art":
            raise ValueError(f"Invalid texture path: {relative}")
        if digest(pack / relative) != entry["sha256"]:
            raise ValueError(f"Texture checksum mismatch: {relative}")
    if previously_active:
        for name, entry in state["files"].items():
            target = Path(name)
            if target.exists() and digest(target) != entry["installed_sha256"]:
                raise ValueError(f"File changed after installation; update manually: {target}")
    for game in ("Generals", "GeneralsZH"):
        runtime = Path.home() / "GeneralsX" / game
        if not runtime.is_dir():
            raise FileNotFoundError(runtime)
        for entry in manifest["files"]:
            target = runtime / entry["path"]
            if not target.resolve().is_relative_to(runtime.resolve()):
                raise ValueError(f"Texture path escapes game directory: {target}")
            key = str(target)
            if key not in state["files"] or not previously_active:
                original = None
                if target.exists():
                    original = f"backups/{game}/{entry['path']}"
                    backup = pack / original
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(target, backup)
                state["files"][key] = {"original": original}
            state["files"][key]["installed_sha256"] = entry["sha256"]
            # Journal before copying so interrupted installs can be restored.
            state["active"] = True
            save_state(state_path, state)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(pack / entry["path"], target)
        options = Path.home() / ".local/share/GeneralsX" / game / "Options.ini"
        text = options.read_text()
        if not previously_active:
            state["preferences"][str(options)] = {}
        keys = state["preferences"].setdefault(str(options), {})
        for key, value in QUALITY.items():
            if key not in keys:
                keys[key] = {"original": preference(text, key), "installed": value}
            text = set_preference(text, key, value)
        save_state(state_path, state)
        options.write_text(text)
    state["version"] = manifest["version"]
    save_state(state_path, state)
    print(f"Installed {len(manifest['files'])} textures in Generals and Zero Hour; engines and trainer unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
