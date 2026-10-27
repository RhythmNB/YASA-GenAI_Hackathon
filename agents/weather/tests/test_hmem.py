"""H-MEM engine test: memories persist, are retrieved by relevance, and keys replace old values."""
from hmem import MemoryRetrievalService, MemoryStoreService


def test_store_retrieve_and_supersede(tmp_path):
    path = tmp_path / "hmem.jsonl"
    store = MemoryStoreService(path=path)
    store.add("Dad is 85 and lives in NYC", tier="long", source="user", confidence=1.0,
              entities=["dad", "NYC"], tags=["household"])
    store.add("LA Saturday: 76°F sunny", tier="short", entities=["LA"], tags=["weather"],
              key="weather:LA:Saturday")
    store.add("LA Saturday: 95°F very hot", tier="short", entities=["LA"], tags=["weather"],
              key="weather:LA:Saturday")

    # Replacement lineage: only the newest LA Saturday memory is active.
    la = [r for r in store.active() if r.key == "weather:LA:Saturday"]
    assert len(la) == 1 and "95°F" in la[0].content and la[0].supersedes

    # Persistence: a fresh store replays the same state from disk.
    reloaded = MemoryStoreService(path=path)
    assert {r.content for r in reloaded.active()} == {r.content for r in store.active()}

    # Relevance: a question about Dad in NYC ranks the household memory first.
    hits = MemoryRetrievalService(reloaded).retrieve("visiting dad in NYC", entities=["dad", "NYC"])
    assert hits and hits[0][1].content.startswith("Dad is 85")
    assert (tmp_path / "ledger.jsonl").exists()


def test_same_key_same_content_is_idempotent(tmp_path):
    store = MemoryStoreService(path=tmp_path / "hmem.jsonl")
    a = store.add("NYC Sunday: 75°F", key="weather:NYC:Sunday")
    b = store.add("NYC Sunday: 75°F", key="weather:NYC:Sunday")
    assert a.id == b.id and len(store.active()) == 1
