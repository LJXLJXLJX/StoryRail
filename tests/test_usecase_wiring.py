import asyncio

from test_director_commands import _visual_project


def test_usecases_share_one_store_one_lock_and_one_registry(tmp_path):
    store, service, document, _ = asyncio.run(_visual_project(str(tmp_path)))
    for usecase in (
        service._media,
        service._generation_observer,
    ):
        assert usecase._store is store
        assert usecase._lock is service._lock
    assert service._media._registry is service._registry
    assert store.read() == document
