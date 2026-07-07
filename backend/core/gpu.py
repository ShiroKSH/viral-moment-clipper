from __future__ import annotations

import subprocess


def detect_nvidia_gpu() -> dict:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return {"available": False, "gpus": []}
    if result.returncode != 0:
        return {"available": False, "gpus": []}
    gpus = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return {"available": bool(gpus), "gpus": gpus}
