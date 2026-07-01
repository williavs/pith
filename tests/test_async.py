"""Async surface — aextract offloads the sync fetch stack to a thread so a caller's event
loop stays free (the real-user blocker: pith didn't play nice with async apps). Offline:
monkeypatch the sync extract so no network is needed; asserts the async delegation + args."""
import asyncio

from pith import Extractor
from pith.core import ExtractResult, Result


def test_aextract_delegates_without_blocking(monkeypatch):
    calls = {}

    def fake_extract(self, urls, **kw):
        calls["urls"], calls["kw"] = urls, kw
        out = ExtractResult()
        out.results = [Result(url=u) for u in urls]
        return out

    monkeypatch.setattr(Extractor, "extract", fake_extract)

    async def main():
        # while aextract runs in a thread, the loop must keep ticking
        ticks = 0
        ex = Extractor()
        task = asyncio.ensure_future(ex.aextract(["https://a", "https://b"], concurrency=4))
        while not task.done():
            ticks += 1
            await asyncio.sleep(0)
        return await task, ticks

    out, ticks = asyncio.run(main())
    assert [r.url for r in out.results] == ["https://a", "https://b"]
    assert calls["kw"]["concurrency"] == 4          # kwargs forwarded
    assert ticks > 0                                # loop advanced while it ran (not blocked)
