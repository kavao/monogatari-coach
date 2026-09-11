"""writing_bridge のエラー形。CHRONOS の CHR コードは使わない。"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from .models import SCHEMA, Severity, StrictModel


class BridgeError(Exception):
    """決定的な入力・照合失敗。"""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        severity: Severity = Severity.ERROR,
        refs: dict[str, Any] | None = None,
        exit_code: int = 2,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.severity = severity
        self.refs = refs or {}
        self.exit_code = exit_code

    def to_item(self) -> "ErrorItem":
        return ErrorItem(
            schema=SCHEMA,
            code=self.code,
            severity=self.severity,
            message=str(self),
            refs=self.refs,
        )


class ErrorItem(StrictModel):
    schema_version: int = Field(default=SCHEMA, alias="schema")
    code: str
    severity: Severity
    message: str
    refs: dict[str, Any] = Field(default_factory=dict)


class ErrorDocument(StrictModel):
    schema_version: int = Field(default=SCHEMA, alias="schema")
    errors: list[ErrorItem] = Field(default_factory=list)

    @classmethod
    def from_items(cls, items: list[ErrorItem]) -> "ErrorDocument":
        return cls(errors=items)
