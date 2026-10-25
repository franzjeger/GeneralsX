#!/usr/bin/env python3
"""Launch the native Zero Hour graphics build with optional external trainer access.

Usage: run-native-zh.py [game flags]
GENERALSX_NATIVE_DIR selects prepared data. GENERALSX_NATIVE_PROFILE can select
a private test XDG data root. GENERALSX_TRAINER_ACCESS=0 disables ptrace access.
"""
import ctypes
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[3]


def main():
    native = Path(os.environ.get("GENERALSX_NATIVE_DIR", REPO.parent / "native")).resolve()
    build = REPO / "build/graphics-lab"
    binary = build / "GeneralsMD/GeneralsXZH"
    runtime = native / "runtime/GeneralsZH"
    if not binary.is_file() or not (native / "manifest.json").is_file():
        raise RuntimeError("Build and prepare native Zero Hour before launching it.")
    profile_path = build / "trainer-profile.json"
    digest = hashlib.sha256(binary.read_bytes()).hexdigest()
    profile = json.loads(profile_path.read_text()) if profile_path.exists() else {}
    if profile.get("binary_sha256") != digest:
        subprocess.run([sys.executable, str(REPO / "scripts/tooling/trainer/build-native-profile.py"),
                        "--binary", str(binary), "--output", str(profile_path)], check=True)
    env = os.environ.copy()
    env.update({"XDG_DATA_HOME": env.get("GENERALSX_NATIVE_PROFILE", str(native / "profiles/default")),
                "CNC_GENERALS_PATH": str(Path.home() / "GeneralsX/Generals"),
                "CNC_GENERALS_ZH_PATH": str(runtime), "CNC_GENERALS_INSTALLPATH": str(runtime),
                "LD_LIBRARY_PATH": f"{build}/_deps/dxvk-src/lib:{build}/bin:" + env.get("LD_LIBRARY_PATH", ""),
                "DXVK_WSI_DRIVER": "SDL3", "DXVK_LOG_LEVEL": env.get("DXVK_LOG_LEVEL", "error"),
                "DXVK_HUD": env.get("DXVK_HUD", "0")})
    if env.get("GENERALSX_TRAINER_ACCESS", "1") == "1":
        # Linux Yama permission is process-local and survives exec. No system-wide
        # ptrace setting changes; the trainer still requires matching hash and ABI.
        libc = ctypes.CDLL(None, use_errno=True)
        libc.prctl.argtypes = [ctypes.c_int] + [ctypes.c_ulong] * 4
        if libc.prctl(0x59616D61, ctypes.c_ulong(-1).value, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), "Could not enable local trainer access")
    logs = native / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    stream = os.open(logs / "zero-hour-launch.log", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.dup2(stream, 1)
    os.dup2(stream, 2)
    os.close(stream)
    os.chdir(runtime)
    os.execve(binary, [str(binary), "-setCwd", str(runtime), "-nologo", "-fullscreen", *sys.argv[1:]], env)


if __name__ == "__main__":
    main()
