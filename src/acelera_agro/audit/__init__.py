"""Audit app — import log_audit from acelera_agro.audit.services."""

__all__ = ["log_audit"]


def __getattr__(name: str):
    if name == "log_audit":
        from acelera_agro.audit.services import log_audit

        return log_audit
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
