from __future__ import annotations

import asyncio
import sys


if sys.platform == "win32":
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except AttributeError:
        pass


import uvicorn

from app.main import cleanup_job_dirs


if __name__ == "__main__":
    try:
        uvicorn.run(
            "app.main:app",
            host="127.0.0.1",
            port=8000,
            loop="asyncio",
            reload=False,
        )
    finally:
        cleanup_job_dirs()
