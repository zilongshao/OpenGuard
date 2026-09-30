"""Bounded asynchronous JSONL logs with idempotent shutdown."""
import atexit
from datetime import datetime, timezone
import json
import os
import queue
import threading

class JSONLEventLogger:
    def __init__(self, log_dir="logs", max_queue_size=4096):
        if max_queue_size < 1:
            raise ValueError("max_queue_size must be positive")
        self.log_dir = log_dir
        os.makedirs(log_dir, exist_ok=True)
        self.log_queue = queue.Queue(maxsize=max_queue_size)
        self._state_lock = threading.Lock()
        self._shutdown_lock = threading.Lock()
        self._closed = False
        self.dropped_events = 0
        self.write_errors = 0
        self.worker_thread = threading.Thread(target=self._write_loop, daemon=True)
        self.worker_thread.start()
        atexit.register(self.shutdown)

    def _write_loop(self):
        while True:
            item = self.log_queue.get()
            try:
                if item is None:
                    return
                safe_id = "".join(c for c in str(item["thread_id"]) if c.isalnum() or c in "-_") or "default"
                with open(os.path.join(self.log_dir, safe_id+".jsonl"), "a", encoding="utf-8") as stream:
                    stream.write(json.dumps(item, ensure_ascii=False)+"\n")
            except Exception as exc:
                self.write_errors += 1
                print(f"[Logger Error] {exc}")
            finally:
                self.log_queue.task_done()

    def log_event(self, thread_id, event, **kwargs):
        item = {**kwargs, "ts": datetime.now(timezone.utc).isoformat(), "thread_id": thread_id, "event": event}
        with self._state_lock:
            if self._closed:
                return False
            try:
                self.log_queue.put_nowait(item)
                return True
            except queue.Full:
                self.dropped_events += 1
                return False

    def shutdown(self):
        with self._shutdown_lock:
            with self._state_lock:
                if self._closed:
                    return
                self._closed = True
            self.log_queue.put(None)
            self.log_queue.join()
            self.worker_thread.join()

audit_logger = JSONLEventLogger()
