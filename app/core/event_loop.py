"""Psycopg requires a selector loop on Windows; avoid deprecated global policies."""

import asyncio
import sys
from collections.abc import Coroutine
from typing import Any


def loop_factory() -> asyncio.AbstractEventLoop:
    return asyncio.SelectorEventLoop() if sys.platform == "win32" else asyncio.new_event_loop()


def run_async[T](coroutine: Coroutine[Any, Any, T]) -> T:
    with asyncio.Runner(loop_factory=loop_factory) as runner:
        return runner.run(coroutine)
