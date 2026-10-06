#!/usr/bin/env python3
"""Apply lab interpreter defaults without replacing unrelated editor settings."""
import json
import os
from pathlib import Path
import sys

import json5

directory = Path(sys.argv[1]) / "User"
directory.mkdir(parents=True, exist_ok=True)
path = directory / "settings.json"
settings = json5.loads(path.read_text()) if path.exists() else {}
settings.update({
    "python.defaultInterpreterPath": "/opt/user-env/venv/bin/python",
    "python.terminal.activateEnvironment": True,
    "python.terminal.activateEnvInCurrentTerminal": True,
    "terminal.integrated.defaultProfile.linux": "bash",
})
environment = settings.setdefault("terminal.integrated.env.linux", {})
environment.update({"VIRTUAL_ENV": "/opt/user-env/venv", "PATH": "/opt/user-env/venv/bin:${env:PATH}"})
temporary = path.with_suffix(f".{os.getpid()}.tmp")
temporary.write_text(json.dumps(settings, indent=2) + "\n")
temporary.replace(path)
