"""Collect hardware measurements using NVIDIA utility access only."""
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import time

from gpu_telemetry import QUERY_FIELDS, parse_nvidia_smi_csv

path = Path("/telemetry/gpu-telemetry.json")
while True:
    sample = {"sampled_at": datetime.now(timezone.utc).isoformat(), "gpus": {}, "error": None}
    try:
        content = subprocess.check_output(["nvidia-smi", "--query-gpu=" + ",".join(QUERY_FIELDS),
            "--format=csv,noheader,nounits"], text=True, stderr=subprocess.PIPE, timeout=5)
        sample["gpus"] = parse_nvidia_smi_csv(content)
        processes = subprocess.check_output(["nvidia-smi", "--query-compute-apps=gpu_uuid,pid",
            "--format=csv,noheader,nounits"], text=True, stderr=subprocess.PIPE, timeout=5)
        uuids = [row[0].strip() for row in csv.reader(processes.splitlines()) if row]
        for gpu in sample["gpus"].values():
            gpu["compute_process_count"] = uuids.count(gpu["uuid"])
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        sample["gpus"] = {}
        sample["error"] = str(exc)[:500]
        print("GPU telemetry:", sample["error"], flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(sample))
    temporary.replace(path)
    time.sleep(3)
