"""A fixed number of worker threads for in-process PDF extraction.

Without the durable queue every upload used to start its own extraction, and
twelve parallel Docling reads used 2.8 GB. Work submitted here runs on at most
``size`` threads; the rest waits in submission order, and its document stays
"queued" until a thread starts it. The threads are daemons: work still waiting
at shutdown is resumed on the next start (see resume_interrupted_extractions).
"""

from __future__ import annotations

import queue
import threading
from concurrent.futures import Future
from typing import Any, Callable


class ExtractionSlots:
    def __init__(self, size: int) -> None:
        self.size = size
        self._work: queue.Queue[tuple[Future, Callable[..., Any], tuple[Any, ...]]] = queue.Queue()
        for index in range(size):
            threading.Thread(target=self._run, name=f"extraction-{index}", daemon=True).start()

    def submit(self, function: Callable[..., Any], *args: Any) -> Future:
        future: Future = Future()
        self._work.put((future, function, args))
        return future

    def _run(self) -> None:
        while True:
            future, function, args = self._work.get()
            if not future.set_running_or_notify_cancel():
                continue
            try:
                future.set_result(function(*args))
            except BaseException as exc:  # noqa: BLE001 - handed to the waiter
                future.set_exception(exc)
