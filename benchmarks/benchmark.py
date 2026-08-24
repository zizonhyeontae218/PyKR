"""대표 36KiB 소스의 양방향 변환 시간과 최대 추적 메모리를 측정한다."""

from __future__ import annotations

import statistics
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from Inverter import pykr_ui as core


PROFILE = core.load_profile(ROOT / "GenderChange.Json")
FORWARD, REVERSE, _ = core.load_extensions(ROOT / "ExtensionPacks")
SOURCE = "\n".join(
    f"def 작업{i}(값{i}):\n"
    f"    결과{i} = [숫자 * 2 for 숫자 in range(값{i}) if 숫자]\n"
    f'    print(f"{i}: {{결과{i}!r}}")\n'
    f"    return sum(결과{i})\n"
    for i in range(250)
)


def convert() -> None:
    kpy = core.python_to_kpy(SOURCE, FORWARD, PROFILE)
    core.kpy_to_python(kpy, REVERSE, PROFILE)


def main() -> None:
    convert()
    samples = []
    for _ in range(7):
        started = time.perf_counter()
        convert()
        samples.append(time.perf_counter() - started)
    tracemalloc.start()
    convert()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(
        f"source={len(SOURCE.encode()):,} bytes "
        f"median={statistics.median(samples) * 1000:.2f} ms "
        f"peak={peak / 1024 / 1024:.2f} MiB"
    )


if __name__ == "__main__":
    main()
