from __future__ import annotations

import sys
from pathlib import Path

API_PATH = Path(__file__).resolve().parents[1] / "apps" / "api"
if str(API_PATH) not in sys.path:
    sys.path.insert(0, str(API_PATH))
