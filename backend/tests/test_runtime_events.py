import asyncio

from app.runtime_events import RuntimeEventBroker


def test_runtime_event_broker_fans_out_revisions():
    async def scenario():
        broker = RuntimeEventBroker(queue_size=8)
        queue = broker.subscribe()
        revision = broker.publish("task.updated", {"id": "abc"})
        await asyncio.sleep(0)
        event = queue.get_nowait()
        assert revision == 1
        assert event.revision == 1
        assert event.type == "task.updated"
        assert event.data == {"id": "abc"}
        broker.unsubscribe(queue)

    asyncio.run(scenario())


def test_runtime_event_broker_bounds_slow_subscribers():
    async def scenario():
        broker = RuntimeEventBroker(queue_size=8)
        queue = broker.subscribe()
        for index in range(20):
            broker.publish("job.updated", {"index": index})
        await asyncio.sleep(0)
        assert queue.qsize() == 8
        events = [queue.get_nowait() for _ in range(queue.qsize())]
        assert events[-1].revision == 20
        assert events[-1].data == {"index": 19}
        broker.unsubscribe(queue)

    asyncio.run(scenario())
