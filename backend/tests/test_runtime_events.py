import asyncio

from app import runtime_events
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


def test_tree_fingerprint_detects_nested_transaction_updates(tmp_path):
    transactions = tmp_path / "network-management" / "transactions"
    transactions.mkdir(parents=True)
    transaction = transactions / "active.json"
    transaction.write_text('{"status":"pending"}', encoding="utf-8")

    initial = runtime_events._tree_fingerprint(transactions)
    transaction.write_text('{"status":"confirmed","revision":2}', encoding="utf-8")
    updated = runtime_events._tree_fingerprint(transactions)

    assert updated != initial


def test_tree_fingerprint_handles_missing_directory(tmp_path):
    assert runtime_events._tree_fingerprint(tmp_path / "missing") == (0, 0, 0)
