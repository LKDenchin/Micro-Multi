import asyncio
import json
import sys
import time

import pytest

from masp.chat_tools import run_chat_tool
from masp.managed_commands import run_cancellable_tool


@pytest.mark.parametrize("cancel_task", [False, True])
def test_cancel_stops_owned_process_before_it_can_write_late_file(tmp_path, cancel_task):
    async def run():
        cancel = asyncio.Event()
        code = "from pathlib import Path; import time; Path('started').write_text('started'); time.sleep(10); Path('late.txt').write_text('late')"
        command = '"' + sys.executable + '" -c "' + code + '"'
        task = asyncio.create_task(
            run_cancellable_tool(
                run_chat_tool,
                tmp_path,
                "run_command",
                json.dumps({"command": command}),
                access_mode="commands",
                cancel_event=cancel,
            )
        )
        deadline = time.monotonic() + 5
        while not (tmp_path / "started").exists():
            assert time.monotonic() < deadline
            await asyncio.sleep(0.02)
        started = time.monotonic()
        if cancel_task:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            cancel.set()
            result = await task
            assert "cancel" in result.lower()
        assert time.monotonic() - started < 2
        assert not (tmp_path / "late.txt").exists()

    asyncio.run(run())
