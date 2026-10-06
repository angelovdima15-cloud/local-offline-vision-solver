import csv
import io
import shutil
import subprocess
import threading


def gpu_snapshot() -> list[dict]:
    executable = shutil.which("nvidia-smi")
    if not executable:
        return []
    try:
        process = subprocess.run([executable, "--query-gpu=name,memory.total,memory.used,utilization.gpu",
                                  "--format=csv,noheader,nounits"], capture_output=True, text=True,
                                 timeout=4, check=True)
        return [{"name": row[0].strip(), "total_megabytes": int(row[1]),
                 "used_megabytes": int(row[2]), "utilization_percent": int(row[3])}
                for row in csv.reader(io.StringIO(process.stdout))]
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return []


class ResourceMonitor:
    def __init__(self):
        self.samples: list[list[dict]] = []
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self):
        while not self.stop.is_set():
            snapshot = gpu_snapshot()
            if snapshot:
                self.samples.append(snapshot)
            self.stop.wait(2)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *_):
        self.stop.set()
        self.thread.join(timeout=5)

    def summary(self) -> dict:
        return {"gpu_peak_used_megabytes": max((g["used_megabytes"] for s in self.samples for g in s), default=None),
                "gpu_samples": len(self.samples), "gpu_last_snapshot": self.samples[-1] if self.samples else [],
                "note": "Device-wide VRAM, includes other processes; sampled every 2 seconds."}

