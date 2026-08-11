from __future__ import annotations

import sqlite3
from types import TracebackType
from typing import Literal


class ClosingConnection(sqlite3.Connection):
    """Commit or roll back a context-managed transaction, then close its FD."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> Literal[False]:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()
