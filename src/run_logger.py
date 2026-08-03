"""Two-stream logging.

- **User stream:** short, plain-English messages shown in the app window / console.
- **Technical stream:** everything (job IDs, dimensions, file paths, full
  tracebacks) written to ``log.txt`` next to the app, for troubleshooting.

Call it like a function for a plain message: ``log("Enhancing with Bloom…")``.
Use ``log.detail(...)`` for technical-only lines and ``log.error(...)`` for problems.
"""

from __future__ import annotations

import logging
import traceback
from pathlib import Path
from typing import Callable


class RunLogger:
    def __init__(self, log_file: str | Path, ui_callback: Callable[[str], None] | None = None) -> None:
        self.ui = ui_callback
        self.log_file = Path(log_file)
        self._logger = logging.getLogger("gbauto")
        self._logger.setLevel(logging.DEBUG)
        self._logger.handlers.clear()
        self._logger.propagate = False
        try:
            fh = logging.FileHandler(self.log_file, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s"))
            self._logger.addHandler(fh)
        except OSError:
            pass  # if the log file can't be opened, keep going without it

    # A bare call is a plain, user-facing message.
    def __call__(self, msg: str) -> None:
        self.user(msg)

    def user(self, msg: str) -> None:
        self._logger.info(msg)
        if self.ui:
            self.ui(msg)

    def detail(self, msg: str) -> None:
        """Technical detail — written to log.txt only."""
        self._logger.debug(msg)

    def error(self, msg: str, exc: BaseException | None = None) -> None:
        self._logger.error(msg)
        if exc is not None:
            self._logger.debug("Traceback:\n" + "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)))
        if self.ui:
            self.ui(f"Problem: {msg}")

    def banner(self, msg: str) -> None:
        self._logger.info("=" * 8 + f" {msg} " + "=" * 8)
        if self.ui:
            self.ui(msg)


def ensure_logger(logger, log_file: str | Path) -> RunLogger:
    """Return a RunLogger. Wraps a plain callable or None so old callers still work."""
    if isinstance(logger, RunLogger):
        return logger
    if callable(logger):
        rl = RunLogger(log_file, ui_callback=logger)
        return rl
    return RunLogger(log_file, ui_callback=None)
