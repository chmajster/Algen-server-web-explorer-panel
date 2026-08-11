from __future__ import annotations

import sqlite3
from types import TracebackType


class ClosingConnection(sqlite3.Connection):
    """Commit or roll back a context-managed transaction, then close its FD."""

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        try:
            return super().__exit__(exc_type, exc_value, traceback)
        finally:
            self.close()
