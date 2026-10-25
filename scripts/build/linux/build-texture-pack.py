#!/usr/bin/env python3
"""Build the data-only terrain, road and vegetation texture pack.

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
EXTRA_TERRAIN.update({f"AsphaltType{i}": "asphalt.png" for i in range(1, 4)})
EXTRA_TERRAIN.update({f"ConcreteType{i}": "concrete.png" for i in range(1, 8)})
EXTRA_TERRAIN["ConcreteMediumType1"] = "concrete.png"
EXTRA_TERRAIN.update({name: "grass.png" for name in (
    "GrassType1", "GrassMediumType10", "GrassMediumType13",
    "GrassLargeType1", "GrassMediumType36")})
EXTRA_TERRAIN.update({name: "snow.png" for name in (
    "SnowType2", "SnowType5", "SnowType7b", "SnowType7c", "SnowLargeType1")})
VEGETATION = {"PTPalm01": ("palm.png", 128), "PTPine01": ("pine.png", 128),
              "PTBush03": ("shrub.png", 128), "PTBush01": ("shrub-dry.png", 128),
              "PTBush02": ("shrub-snow.png", 128), "PTBush04": ("shrub-dry.png", 128),
              "PTBush05": ("shrub-snow.png", 64), "PTBush06": ("shrub.png", 64),
              "PTBush07": ("shrub-dry.png", 64), "PTBush11": ("shrub.png", 64),
              "PTBush12": ("shrub-snow.png", 64)}


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
    if len(selected) != 38:
        raise ValueError(f"Expected 38 known terrain types, found {len(selected)}")
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
    terrain_count = len(selected)
    for name, (source, tree_size) in VEGETATION.items():
        image = Image.open(art / source).convert("RGBA")
        if image.getchannel("A").getextrema() != (0, 255):
            raise ValueError(f"Vegetation source needs real transparency: {source}")
        # Optimized trees use a fixed 2048px atlas and count 256px images as
        # sixteen legacy cells (expectedTileCount=0). Use 128px/4 cells to
        # preserve atlas headroom. Ordinary model-drawn trees can use 512px DDS.
        for relative, size in ((Path("Art/Terrain") / f"{name}.tga", (tree_size, tree_size)),
                               (Path("Art/Textures") / f"{name.lower()}.dds", (512, 512))):
            target = pack / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            resized = image.resize(size, Image.Resampling.LANCZOS)
            if relative.suffix == ".tga":
                resized.save(target, compression=None)
            else:
                png = intermediates / f"{name}.png"
                resized.save(png)
                subprocess.run(["magick", str(png), "-define", "dds:compression=dxt5",
                                "-define", "dds:mipmaps=9", str(target)], check=True)
            files.append({"path": relative.as_posix(), "source": source,
                          "category": "vegetation", "size": list(size),
                          "alpha": "Generated transparent foliage; original normalized UV layout",
                          "sha256": hashlib.sha256(target.read_bytes()).hexdigest()})
    manifest = {"version": "3.1", "engine": "GeneralsX 1.0.4 (256px terrain cells), data-only",
                "files": files}
    (pack / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built {len(files)} textures in {pack} ({terrain_count} terrain, one road, {len(VEGETATION)*2} vegetation files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
