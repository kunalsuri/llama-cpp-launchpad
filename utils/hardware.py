#!/usr/bin/env python3
"""llama-cpp-launchpad: hardware detection.

Reads this machine's RAM, CPU and GPU (and whether your llama.cpp build can use the GPU).
Used by model_setup.py, and by scripts/win/dev-setup.ps1 to write a report file.

Python standard library only. Read-only: it runs nvidia-smi / sysctl / llama-server --list-devices,
reads the OS memory counters, and (when asked) writes one file: <project>/.hardware.env.
It records no host name, user name, serial numbers or IP addresses.

Usage:
  hardware.py                 write <project>/.hardware.env and print a one-line summary
  hardware.py --out FILE      write the report somewhere else
  hardware.py --print         print the report instead of writing it

Settings (optional environment variables):
  LP_RAM_MB, LP_VRAM_MB   override detected memory (if detection is wrong)
  LP_GPU_USABLE           1/0 = force "the llama.cpp build can use the GPU"
  LLAMA_SERVER            path to llama-server (default: auto-detected)
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import platform
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_NAME = ".hardware.env"


class Hw:
    def __init__(self, ram_mb=0, cores=1, gpu_kind="none", gpu_name="", vram_mb=0, gpu_usable=False):
        self.ram_mb, self.cores = ram_mb, cores
        self.gpu_kind, self.gpu_name = gpu_kind, gpu_name        # none | nvidia | apple | gpu
        self.vram_mb, self.gpu_usable = vram_mb, gpu_usable

    def sig(self) -> str:
        return f"{self.ram_mb}-{self.vram_mb}-{self.gpu_kind}-{int(self.gpu_usable)}-{self.cores}"


def run_cmd(args: list, timeout: int = 20) -> str:
    """Run a program (never through a shell) and return its stdout, or '' on any failure."""
    try:
        done = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return done.stdout + done.stderr
    except (OSError, subprocess.SubprocessError):
        return ""


def find_llama_server() -> str:
    cands = [os.environ.get("LLAMA_SERVER", ""), shutil.which("llama-server") or "",
             str(ROOT / "bin" / "llama-server"), str(ROOT / "bin" / "llama-server.exe"),
             str(Path.home() / "llama.cpp" / "build" / "bin" / "llama-server")]
    for c in cands:
        if c and os.path.isfile(c) and os.access(c, os.X_OK):
            return c
    return ""


def gpu_usable() -> bool:
    """Does the installed llama.cpp build offer a GPU backend?"""
    srv = find_llama_server()
    if not srv:
        return False
    return bool(re.search(r"CUDA|Vulkan|ROCm|HIP|SYCL|Metal", run_cmd([srv, "--list-devices"]), re.I))


def read_ram_mb() -> int:
    system = platform.system()
    try:
        if system == "Linux":
            path = os.environ.get("MEMINFO_FILE", "/proc/meminfo")
            for line in Path(path).read_text().splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) // 1024
        elif system == "Darwin":
            return int(run_cmd(["sysctl", "-n", "hw.memsize"]).strip()) // 1048576
        elif system == "Windows":
            import ctypes

            class MemStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                            ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                            ("totpage", ctypes.c_ulonglong), ("availpage", ctypes.c_ulonglong),
                            ("totvirt", ctypes.c_ulonglong), ("availvirt", ctypes.c_ulonglong),
                            ("ext", ctypes.c_ulonglong)]
            st = MemStatus()
            st.length = ctypes.sizeof(MemStatus)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st))
            return int(st.total) // 1048576
    except (OSError, ValueError, IndexError):
        pass
    return 0


def read_cpu_name() -> str:
    """Marketing name of the CPU, e.g. 'AMD Ryzen 7 5800X'. Empty if unknown."""
    system = platform.system()
    try:
        if system == "Windows":
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0") as key:
                return " ".join(str(winreg.QueryValueEx(key, "ProcessorNameString")[0]).split())
        if system == "Linux":
            for line in Path("/proc/cpuinfo").read_text().splitlines():
                if line.lower().startswith(("model name", "hardware")):
                    return " ".join(line.partition(":")[2].split())
        if system == "Darwin":
            return run_cmd(["sysctl", "-n", "machdep.cpu.brand_string"]).strip()
    except (OSError, ValueError, ImportError):
        pass
    return platform.processor()


def detect_hw() -> Hw:
    hw = Hw(ram_mb=read_ram_mb(), cores=os.cpu_count() or 1)
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        hw.gpu_kind, hw.gpu_name, hw.gpu_usable = "apple", "Apple Silicon (unified memory)", True
    else:
        out = run_cmd(["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"])
        line = out.strip().splitlines()[0] if out.strip() else ""
        name, _, vram = line.rpartition(", ")
        if name and vram.strip().isdigit() and int(vram) > 0:
            hw.gpu_kind, hw.gpu_name, hw.vram_mb = "nvidia", name, int(vram)
            forced = os.environ.get("LP_GPU_USABLE")
            hw.gpu_usable = (forced == "1") if forced is not None else gpu_usable()
    if os.environ.get("LP_RAM_MB", "").isdigit():
        hw.ram_mb = int(os.environ["LP_RAM_MB"])
    if os.environ.get("LP_VRAM_MB", "").isdigit():
        hw.vram_mb = int(os.environ["LP_VRAM_MB"])
        if hw.gpu_kind == "none":
            hw.gpu_kind, hw.gpu_name, hw.gpu_usable = "gpu", "GPU (set by you)", True
    return hw


# --- Report file -------------------------------------------------------------------------------
def report_items(hw: Hw) -> list:
    """(KEY, value) pairs for the report. Hardware facts only: no host name, user name or addresses."""
    server = find_llama_server()
    mode = "gpu" if hw.gpu_usable else "cpu"
    return [
        ("HW_GENERATED_AT", dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")),
        ("HW_OS", f"{platform.system()} {platform.release()}"),
        ("HW_ARCH", platform.machine()),
        ("HW_CPU_NAME", read_cpu_name()),
        ("HW_CPU_THREADS", hw.cores),
        ("HW_RAM_MB", hw.ram_mb),
        ("HW_GPU_KIND", hw.gpu_kind),
        ("HW_GPU_NAME", hw.gpu_name),
        ("HW_VRAM_MB", hw.vram_mb),
        ("HW_GPU_USABLE_BY_LLAMACPP", str(hw.gpu_usable).lower()),
        ("HW_LLAMA_SERVER", server),
        ("HW_RECOMMENDED_MODE", mode),
        ("HW_SIGNATURE", hw.sig()),
    ]


def render_report(hw: Hw) -> str:
    lines = ["# Generated by utils/hardware.py (scripts\\win\\dev-setup.ps1 runs it) - do not edit, do not commit."]
    for key, value in report_items(hw):
        text = str(value).replace("\r", " ").replace("\n", " ").replace('"', '\\"')
        lines.append(f'{key}="{text}"')
    return "\n".join(lines) + "\n"


def write_report(path: Path, hw: Hw) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(render_report(hw), encoding="utf-8")
    os.replace(tmp, path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Detect RAM, CPU and GPU and write a report file.")
    ap.add_argument("--out", type=Path, default=ROOT / REPORT_NAME, help=f"report file (default: <project>/{REPORT_NAME})")
    ap.add_argument("--print", action="store_true", dest="show", help="print the report instead of writing it")
    args = ap.parse_args(argv)
    hw = detect_hw()
    if args.show:
        sys.stdout.write(render_report(hw))
        return 0
    write_report(args.out, hw)
    gpu = f"{hw.gpu_name}, {hw.vram_mb // 1024} GB" if hw.gpu_kind in ("nvidia", "gpu") else hw.gpu_name or "no GPU"
    print(f"{(hw.ram_mb + 512) // 1024} GB RAM, {hw.cores} threads, {gpu} -> {args.out}")
    return 0 if hw.ram_mb else 1


if __name__ == "__main__":
    sys.exit(main())
