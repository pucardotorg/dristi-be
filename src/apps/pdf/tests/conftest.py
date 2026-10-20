"""Fixtures shared by the PDF tests."""

import pytest
from django.core.cache import cache


@pytest.fixture(autouse=True)
def in_memory_file_storage(settings):
    """Keep apps.files content in memory so tests never touch disk."""
    settings.STORAGES = {
        **settings.STORAGES,
        "files": {"BACKEND": "django.core.files.storage.InMemoryStorage"},
    }


@pytest.fixture(autouse=True)
def clear_cache():
    """Every test starts with an empty config/localization cache."""
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def broker():
    """Return the stub broker with every queue emptied."""
    import dramatiq

    stub = dramatiq.get_broker()
    stub.flush_all()
    yield stub
    stub.flush_all()


@pytest.fixture
def no_retry_delay(settings):
    """Retry immediately so retry paths can run inside a test."""
    settings.PDF_RETRY_DELAY_BASE_SECONDS = 0
    settings.PDF_RETRY_DELAY_MAX_SECONDS = 0


def drain(broker, queue="pdf", limit=500):
    """Run every queued (and delayed) message on ``queue`` in-process.

    Messages enqueued while draining are run too, so a whole job -- fan-out,
    retries and finalization -- completes inside the test. Returns the number
    of messages processed.
    """
    from dramatiq import Message
    from dramatiq.common import dq_name

    processed = 0
    while processed < limit:
        message = None
        for name in (queue, dq_name(queue)):
            pending = broker.queues.get(name)
            if pending is not None and not pending.empty():
                message = Message.decode(pending.get_nowait())
                break
        if message is None:
            return processed
        actor = broker.get_actor(message.actor_name)
        actor.fn(*message.args, **message.kwargs)
        processed += 1
    raise AssertionError("drain() did not converge; possible enqueue loop.")
