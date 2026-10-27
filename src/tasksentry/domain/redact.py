"""Tenant-local reversible redaction for untrusted ticket and SOP text."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from ipaddress import ip_address
from typing import Any

EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")
IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6_RE = re.compile(r"(?<![\w:])[0-9A-Fa-f:]*:[0-9A-Fa-f:]+(?![\w:])")
SECRET_RE = re.compile(
    r"(?ix)"
    r"(?<![A-Za-z0-9])(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9_-]{16,}|"
    r"xox[baprs]-[A-Za-z0-9-]{16,}|AKIA[0-9A-Z]{16}|"
    r"eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})"
    r"(?![A-Za-z0-9])"
)
KEY_VALUE_RE = re.compile(
    r"(?i)(?P<prefix>\b(?:api[_-]?key|access[_-]?token|token|secret|password|authorization)\s*[:=]\s*)"
    r"(?P<value>\"[^\"]+\"|'[^']+'|[^\s,;]+)"
)


@dataclass(frozen=True)
class RedactionStats:
    """Counts that can be included in a dataset card without exposing values."""

    replacements: int = 0
    emails: int = 0
    ips: int = 0
    secrets: int = 0


class TenantRedactor:
    """Redact values using a map scoped to one tenant and one redactor instance.

    The reversible map is intentionally kept out of returned records.  Callers
    that need restoration must retain this object inside the tenant boundary.
    """

    def __init__(self, tenant_id: str, *, redact_ips: bool = False) -> None:
        if not tenant_id.strip():
            raise ValueError("tenant_id must not be blank")
        self.tenant_id = tenant_id
        self.redact_ips = redact_ips
        self._forward: dict[str, str] = {}
        self._reverse: dict[str, str] = {}
        self._counts = {"replacements": 0, "emails": 0, "ips": 0, "secrets": 0}

    def _placeholder(self, kind: str, original: str) -> str:
        existing = self._forward.get(original)
        if existing is not None:
            return existing
        number = sum(1 for value in self._reverse if value.startswith(f"<TS_{kind}_")) + 1
        token = f"<TS_{kind}_{number:04d}>"
        self._forward[original] = token
        self._reverse[token] = original
        self._counts["replacements"] += 1
        self._counts[{"EMAIL": "emails", "IP": "ips", "SECRET": "secrets"}[kind]] += 1
        return token

    def _replace_secret_value(self, match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        value = match.group("value")
        quote = value[0] if value[:1] in {"'", '"'} else ""
        raw = value[1:-1] if quote else value
        if raw in self._reverse or raw.startswith("<TS_"):
            return match.group(0)
        return prefix + quote + self._placeholder("SECRET", raw) + quote

    def redact_text(self, text: str) -> str:
        """Return redacted text; repeated calls are idempotent."""
        redacted = KEY_VALUE_RE.sub(self._replace_secret_value, text)
        redacted = SECRET_RE.sub(
            lambda match: self._placeholder("SECRET", match.group(0)), redacted
        )
        redacted = EMAIL_RE.sub(lambda match: self._placeholder("EMAIL", match.group(0)), redacted)
        if self.redact_ips:
            redacted = IPV6_RE.sub(self._replace_ipv6, redacted)
            redacted = IPV4_RE.sub(lambda match: self._placeholder("IP", match.group(0)), redacted)
        return redacted

    def _replace_ipv6(self, match: re.Match[str]) -> str:
        value = match.group(0)
        try:
            ip_address(value)
        except ValueError:
            return value
        return self._placeholder("IP", value)

    def redact(self, text: str) -> str:
        """Short alias for :meth:`redact_text`."""
        return self.redact_text(text)

    def redact_record(self, value: Any) -> Any:
        """Recursively redact string values while preserving record structure."""
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, Mapping):
            return {str(key): self.redact_record(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact_record(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact_record(item) for item in value)
        return value

    def restore_text(self, redacted: str) -> str:
        """Restore placeholders using only this tenant-local map."""
        restored = redacted
        for token in sorted(self._reverse, key=len, reverse=True):
            restored = restored.replace(token, self._reverse[token])
        return restored

    def export_token_map(self) -> dict[str, str]:
        """Return a copy of the sensitive map for secure tenant-local storage."""
        return dict(self._forward)

    @property
    def stats(self) -> RedactionStats:
        """Return aggregate counts without exposing redacted values."""
        return RedactionStats(**self._counts)
