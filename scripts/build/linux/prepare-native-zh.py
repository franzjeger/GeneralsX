#!/usr/bin/env python3
"""Prepare normal native Zero Hour with HD foliage and shared existing saves.

Usage: prepare-native-zh.py [--native-dir DIR] [--pack-dir DIR]
Keeps retail archives read-only, and native preferences separate from Flatpak.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil

from PIL import Image

REPO = Path(__file__).resolve().parents[3]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-dir", type=Path, default=REPO.parent / "native")
    parser.add_argument("--pack-dir", type=Path, default=REPO.parent / "texture-pack")
    args = parser.parse_args()
    native, pack = args.native_dir.resolve(), args.pack_dir.resolve()
    retail = Path.home() / "GeneralsX/GeneralsZH"
    source_profile = Path.home() / ".local/share/GeneralsX/GeneralsZH"
    runtime = native / "runtime/GeneralsZH"
    runtime.mkdir(parents=True, exist_ok=True)
    for item in retail.iterdir():
        if not (item.name.lower().endswith(".big") or item.name == "Data"):
            continue
        target = runtime / item.name
        if not target.exists():
            target.symlink_to(item.resolve(), target_is_directory=item.is_dir())
    manifest = json.loads((pack / "manifest.json").read_text())
    installed = []
    for entry in manifest["files"]:
        relative = Path(entry["path"])
        if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "Art":
            raise ValueError(f"Invalid art path: {relative}")
        source, target = pack / relative, runtime / relative
        if hashlib.sha256(source.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Texture checksum mismatch: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry.get("category") == "vegetation" and relative.suffix == ".tga":
            artwork = REPO / "assets/graphics-lab" / entry["source"]
            Image.open(artwork).convert("RGBA").resize((256, 256), Image.Resampling.LANCZOS).save(target, compression=None)
        else:
            shutil.copyfile(source, target)
        installed.append({"path": entry["path"], "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    profile = native / "profiles/default/GeneralsX/GeneralsZH"
    profile.mkdir(parents=True, exist_ok=True)
    for item in source_profile.iterdir():
        target = profile / item.name
        if target.exists() or target.is_symlink():
            continue
        if item.is_dir():
            target.symlink_to(item.resolve(), target_is_directory=True)
        else:
            shutil.copyfile(item, target)
    # This file belongs to the separate native profile; release preferences stay intact.
    options = profile / "Options.ini"
    text = options.read_text()
    for key, value in {"TextureFilter": "Anisotropic", "AnisotropyLevel": "16",
                       "TextureReduction": "0", "AntiAliasing": "4",
                       "DynamicLOD": "no", "WaterReflections": "yes"}.items():
        line = f"{key} = {value}"
        if re.search(r"^" + key + r"\s*=", text, re.M):
            text = re.sub(r"^" + key + r"\s*=.*$", line, text, flags=re.M)
        else:
            text += "\n" + line + "\n"
    options.write_text(text)
    (native / "manifest.json").write_text(json.dumps({"pack_version": manifest["version"],
        "files": installed, "runtime": str(runtime), "profile": str(profile),
        "shared_save_directory": str((source_profile / "Save").resolve())}, indent=2) + "\n")
    print(f"Prepared native Zero Hour: {len(installed)} textures; existing save directory shared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
