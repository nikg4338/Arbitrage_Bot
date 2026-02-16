from __future__ import annotations

import importlib.util
import json
import sys
import sysconfig
from datetime import datetime, timezone
from pathlib import Path
from types import ModuleType
from typing import Any


def _load_stdlib_logging() -> ModuleType:
    stdlib_dir = Path(sysconfig.get_paths()["stdlib"])
    logging_path = stdlib_dir / "logging" / "__init__.py"
    spec = importlib.util.spec_from_file_location("_stdlib_logging", logging_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("unable to locate stdlib logging module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_std_logging = _load_stdlib_logging()


class JsonFormatter(_std_logging.Formatter):
    def format(self, record: Any) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        if hasattr(record, "context"):
            payload["context"] = getattr(record, "context")
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    root = _std_logging.getLogger()
    root.setLevel(level.upper())

    handler = _std_logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root.handlers.clear()
    root.addHandler(handler)


# Re-export stdlib logging API so `import logging` in this package remains safe.
for _name in dir(_std_logging):
    if _name.startswith("__"):
        continue
    if _name in globals():
        continue
    globals()[_name] = getattr(_std_logging, _name)
