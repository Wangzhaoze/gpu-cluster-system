"""NVIDIA CSV parsing and freshness checks shared with the utility monitor."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path

QUERY_FIELDS = ["index", "uuid", "pci.bus_id", "name", "driver_version", "memory.total",
                "memory.used", "memory.free", "utilization.gpu", "utilization.memory",
                "temperature.gpu", "power.draw", "power.limit", "fan.speed",
                "clocks.current.graphics", "clocks.current.memory"]
METRIC_FIELDS = ["memory_total_mb", "memory_used_mb", "memory_free_mb", "utilization_percent",
                 "memory_utilization_percent", "temperature_c", "power_w", "power_limit_w",
                 "fan_percent", "graphics_clock_mhz", "memory_clock_mhz"]


def number(value: str):
    try:
        return float(value.strip())
    except ValueError:
        return None


def parse_nvidia_smi_csv(content: str) -> dict[str, dict]:
    result = {}
    for row in csv.reader(content.splitlines(), skipinitialspace=True):
        if not row:
            continue
        if len(row) != len(QUERY_FIELDS):
            raise ValueError("Unexpected NVIDIA telemetry column count")
        index = int(row[0])
        result[str(index)] = {"gpu_index": index, "uuid": row[1].strip(),
            "pci_bus_id": row[2].strip(), "name": row[3].strip(), "driver_version": row[4].strip(),
            **dict(zip(METRIC_FIELDS, map(number, row[5:]))) }
    return result


def read_telemetry(path: Path, mode: str) -> dict:
    if mode != "local-gpu-docker":
        return {"status": "mock", "sampled_at": None, "gpus": {}, "error": None}
    try:
        sample = json.loads(path.read_text())
        sampled = datetime.fromisoformat(sample["sampled_at"])
        age = (datetime.now(timezone.utc) - sampled).total_seconds()
        if age < -5 or age > 15:
            return {"status": "stale", "sampled_at": sample["sampled_at"], "gpus": {}, "error": "GPU 监控数据已过期"}
        if sample.get("error") or not sample.get("gpus"):
            return {"status": "unavailable", "sampled_at": sample["sampled_at"], "gpus": {}, "error": sample.get("error") or "未读取到显卡"}
        return {"status": "online", **sample}
    except (OSError, ValueError, KeyError, TypeError):
        return {"status": "unavailable", "sampled_at": None, "gpus": {}, "error": "GPU 监控暂不可用"}
