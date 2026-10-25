# Local graphics sources

This directory contains the versioned source artwork for the native Linux graphics work in [franzjeger/GeneralsX](https://github.com/franzjeger/GeneralsX), on branch `local/graphics-lab`.

| Sources | Use |
| --- | --- |
| `sand.png`, `dirt.png`, `rock.png`, `cliff.png` | Desert terrain |
| `asphalt.png`, `concrete.png` | Paved terrain |
| `grass.png`, `snow.png` | Temperate and winter terrain |
| `road-surface.png` | Dirt-road material |
| `palm.png`, `pine.png` | Palm and pine foliage/bark UV textures |
| `shrub.png`, `shrub-dry.png`, `shrub-snow.png` | Green, dry and winter shrubs |
| `provenance.json` | Built-in imagegen prompts, reference descriptions and conversion details |

Build the game-ready TGA/DDS files from the repository root:

```bash
python scripts/build/linux/build-texture-pack.py
```

The generated output and local installation backups live beside the repository in `../texture-pack/`. These are build/deployment files; the editable artwork and builder remain here in Git. Original retail archives supply atlas dimensions and the road opacity mask and are not copied into the repository.

Install or restore in the normal games:

```bash
python scripts/build/linux/install-texture-pack.py
python scripts/build/linux/install-texture-pack.py --restore
```

The normal release pack uses smaller optimized-tree TGAs compatible with the unchanged engine and trainer. Its water reflections are disabled as a workaround for the release engine's foliage visibility bug.

The native development engine fixes visibility caching between mirror/main passes, legacy half-image UV cropping and native HD foliage grid selection in `Core/GameEngineDevice/Source/W3DDevice/GameClient/W3DTreeBuffer.cpp`. The enhanced lab uses separate 256px foliage TGAs and can keep water reflections enabled:

```bash
scripts/build/linux/build-graphics-lab.sh
python scripts/build/linux/prepare-graphics-lab.py
scripts/build/linux/run-graphics-lab.sh enhanced
```

The lab has its own runtime, settings and test map under `../development/`. The existing release trainer does not attach to this development executable.
