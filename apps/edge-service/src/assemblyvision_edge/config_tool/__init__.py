"""Interactive configuration manager (``assemblyvision config``).

Provides guided editing, aggregate validation, and backup/rollback for edge
pipeline/rule/manifest and central ``.env`` configuration, with an
environment dimension (development vs production) and four languages.
"""

from __future__ import annotations

from .backup import BackupEntry, create_backup, list_backups, restore_backup
from .edit import run_edit
from .i18n import DEFAULT_LANG, SUPPORTED_LANGS, Lang, lang_name, t
from .validate import (
    Env,
    ValidationIssue,
    parse_env_file,
    validate_all,
    validate_central_env,
    validate_edge,
)

__all__ = [
    "BackupEntry",
    "DEFAULT_LANG",
    "Env",
    "Lang",
    "SUPPORTED_LANGS",
    "ValidationIssue",
    "create_backup",
    "lang_name",
    "list_backups",
    "parse_env_file",
    "restore_backup",
    "run_edit",
    "t",
    "validate_all",
    "validate_central_env",
    "validate_edge",
]
