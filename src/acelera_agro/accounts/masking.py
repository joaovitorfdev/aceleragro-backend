"""Utilities to mask sensitive personal data in logs."""

from __future__ import annotations

import re

_CPF_DIGITS = re.compile(r"\d{11}")
_CPF_FORMATTED = re.compile(r"\d{3}\.?\d{3}\.?\d{3}-?\d{2}")


def mask_cpf(value: str | None) -> str:
    if not value:
        return ""
    digits = re.sub(r"\D", "", value)
    if len(digits) != 11:
        return "***.***.***-**"
    return f"***.***.***-{digits[-2:]}"


def mask_cpf_in_text(text: str) -> str:
    """Replace CPF-like sequences in free text with a masked form."""

    def _repl(match: re.Match[str]) -> str:
        return mask_cpf(match.group(0))

    return _CPF_FORMATTED.sub(_repl, text)
