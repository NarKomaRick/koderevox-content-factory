import asyncio

from app.tasks.processing import run_async


async def current_loop_id() -> int:
    return id(asyncio.get_running_loop())


def test_task_async_runner_reuses_one_event_loop() -> None:
    assert run_async(current_loop_id()) == run_async(current_loop_id())
