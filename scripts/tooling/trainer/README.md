# Zero Hour trainer

The trainer supports the installed Linux Flatpak 1.0.4 binary and this fork's native Linux graphics build. The UI and existing desktop launcher retain the original money, general points, 20x production, instant research, local invulnerability and instant cooldown controls.

Run:

```bash
python scripts/tooling/trainer/zero_hour_trainer.py
```

Start the game with `scripts/build/linux/run-native-zh.py`. It enables process-local Linux Yama access before executing the game, so the separately opened trainer can attach. It does not change system-wide ptrace settings. Set `GENERALSX_TRAINER_ACCESS=0` to disable this access.

Native profiles are generated from the exact unstripped executable:

```bash
python scripts/tooling/trainer/build-native-profile.py \
  --binary build/graphics-lab/GeneralsMD/GeneralsXZH \
  --output build/graphics-lab/trainer-profile.json
```

The generator checks 44 DWARF field offsets, the body-interface offset, shared-timer list layout and virtual-function slots. It obtains symbol addresses from ELF metadata and binds the result to the executable's SHA-256. The launcher regenerates a stale profile before startup; unsupported ABI changes stop profile generation. The trainer still revalidates live player/object identity, ownership and module types before writing.

Tests cover local/AI boundaries, captured and recycled objects, temporary Sneak Attack tunnel objects, shared cooldowns and research queues. They also repeat those checks with relocated engine addresses:

```bash
python -m unittest discover -s scripts/tooling/trainer -v
```

For an isolated test process, `--pid PID` selects it explicitly. Test/checkpoint sessions should use a separate `GENERALSX_NATIVE_PROFILE`; the normal native profile shares the existing save directory.
