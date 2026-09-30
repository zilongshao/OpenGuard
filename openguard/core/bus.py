import asyncio
from contextlib import suppress

task_queue = asyncio.Queue()

async def emit_task(content: str):
    await task_queue.put(content)

async def stop_workers(worker, heartbeat_worker, queue):
    """Stop all producers before placing the consumer's exit sentinel."""
    heartbeat_worker.cancel()
    with suppress(asyncio.CancelledError):
        await heartbeat_worker
    await queue.put("/exit")
    await queue.join()
    await worker
