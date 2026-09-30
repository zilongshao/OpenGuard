"""Atomic JSON task writes. Callers serialize access using tasks_lock."""
import json
import os
from pathlib import Path
import tempfile

def write_tasks_atomic(path, tasks):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target.parent,
                                         prefix=target.name+".", suffix=".tmp", delete=False) as stream:
            temporary = stream.name
            json.dump(tasks, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)
