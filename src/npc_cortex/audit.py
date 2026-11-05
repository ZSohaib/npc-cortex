"""Audit log (spec 3.10)."""

from __future__ import annotations

__all__ = ["AuditLog"]


class AuditLog:
    def __init__(self) -> None:
        self.records: list = []
