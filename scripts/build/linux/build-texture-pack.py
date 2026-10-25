#!/usr/bin/env python3
"""Build the data-only terrain/road pack from generated material sources.

Usage: build-texture-pack.py [--pack-dir DIR]
Retail atlases provide dimensions, tile counts and road UV opacity only.
Imagegen provides all replacement colour artwork. No retail archives are edited.
"""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import subprocess

from PIL import Image

REPO = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("graphics_lab", Path(__file__).with_name("prepare-graphics-lab.py"))
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)
EXTRA_TERRAIN = {"SandMediumType5": "dirt.png", "SandMediumType5b": "dirt.png",
                 "DirtMediumType12": "dirt.png", "DirtMediumType13": "dirt.png",
                 "DirtMediumType14": "dirt.png", "CliffLargeType1": "cliff.png",
                 "CliffLargeType12": "cliff.png"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack-dir", type=Path, default=REPO.parent / "texture-pack")
    args = parser.parse_args()
    pack = args.pack_dir.resolve()
    art = REPO / "assets/graphics-lab"
    base = Path.home() / "GeneralsX/Generals"
    zh = Path.home() / "GeneralsX/GeneralsZH"
    definitions = lab.extract(zh / "INIZH.big", {"data/ini/terrain.ini"})["data/ini/terrain.ini"].decode()
    selected = {}
    for name, body in re.findall(r"^Terrain\s+(\S+)\s*\n(.*?)^End", definitions, re.M | re.S):
        source = EXTRA_TERRAIN.get(name)
        if name in lab.SAND_CLASSES:
            source = "sand.png"
        elif name in lab.ROCK_CLASSES:
            source = "rock.png"
        if source:
            texture = re.search(r"Texture\s*=\s*(\S+)", body)[1]
            selected[f"art/terrain/{texture}".lower()] = (name, texture, source)
    if len(selected) != 17:
        raise ValueError(f"Expected 17 known terrain types, found {len(selected)}")
    stock = lab.extract(base / "Terrain.big", set(selected))
    stock.update(lab.extract(zh / "TerrainZH.big", set(selected)))
    files = []
    for key, (name, texture, source) in selected.items():
        original = Image.open(io.BytesIO(stock[key]))
        width, height = original.size
        relative = Path("Art/Terrain") / texture
        target = pack / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        size = (width * 4, height * 4)
        Image.open(art / source).convert("RGB").resize(size, Image.Resampling.LANCZOS).save(target, compression=None)
        files.append({"path": relative.as_posix(), "terrain": name, "source": source,
                      "original_size": [width, height], "size": size,
                      "tile_grid": [width // 64, height // 64],
                      "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    relative = Path("Art/Textures/trdirtroad4.dds")
    original_data = lab.extract(base / "Textures.big", {relative.as_posix().lower()})[relative.as_posix().lower()]
    original = Image.open(io.BytesIO(original_data)).convert("RGBA")
    size = (1024, 1024)
    # Asset-channel packaging: keep the retail atlas's opacity/UV geometry and
    # use generated surface colour, avoiding regenerated road-island boundaries.
    colour = Image.open(art / "road-surface.png").convert("RGB").resize(size, Image.Resampling.LANCZOS)
    alpha = original.getchannel("A").resize(size, Image.Resampling.BILINEAR)
    colour.putalpha(alpha)
    intermediates = pack / "build"
    intermediates.mkdir(parents=True, exist_ok=True)
    png = intermediates / "road-atlas.png"
    colour.save(png)
    target = pack / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["magick", str(png), "-define", "dds:compression=dxt5",
                    "-define", "dds:mipmaps=10", str(target)], check=True)
    with Image.open(target) as result:
        if result.size != size or result.mode != "RGBA":
            raise ValueError("Invalid road DDS output")
    files.append({"path": relative.as_posix(), "source": "road-surface.png",
                  "original_size": list(original.size), "size": list(size),
                  "alpha": "Original road-atlas opacity, scaled without moving UV islands",
                  "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    manifest = {"version": "2.0", "engine": "GeneralsX 1.0.4 (256px terrain cells), data-only",
                "files": files}
    (pack / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built {len(files)} textures in {pack} (17 terrain atlases and one road atlas).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
