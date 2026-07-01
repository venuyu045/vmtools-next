"""Entry point for uvicorn when started from the backend/ directory.

Ensures src/ is on sys.path so that 'vmtools_next' can be imported
regardless of the working directory.
"""
import sys
from pathlib import Path

_src = Path(__file__).resolve().parent / "src"
if str(_src) not in sys.path:
    sys.path.insert(0, str(_src))

# Import sio_app (Socket.IO ASGI wrapper) — NOT the raw FastAPI `app`.
# Without the Socket.IO ASGI wrapper, real-time terminal output won't work.
from vmtools_next.main import sio_app  # noqa: E402, F401

# Re-export with name `app` so uvicorn can discover it via `main:app`
app = sio_app
