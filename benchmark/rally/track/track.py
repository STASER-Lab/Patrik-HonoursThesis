"""Rally runner for the repository queries in benchmark.queries.

Rally times the exact query functions that check_answers verifies. They are
synchronous and written for the project's client, so they run in a thread and
reach Elasticsearch through LayoutClient, which forwards each call to Rally's
async client.
"""

import asyncio
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


class LayoutClient:
    """The two client methods the queries use: search and esql.query."""

    def __init__(self, es, loop):
        self._es = es
        self._loop = loop
        self.esql = self

    def _wait(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def search(self, **kwargs):
        return self._wait(self._es.search(**kwargs))

    def query(self, query):
        return self._wait(
            self._es.perform_request(
                "POST",
                "/_query",
                headers={
                    "accept": "application/json",
                    "content-type": "application/json",
                },
                body={"query": query},
            )
        )


async def layout_query(es, params):
    module = importlib.import_module(f"benchmark.queries.{params['query']}")
    run = getattr(module, params["layout"])
    client = LayoutClient(es, asyncio.get_running_loop())
    # Rally keeps the earliest start and the latest end, so these two calls make
    # the service time cover the whole function, not just its requests.
    es.on_request_start()
    # to_thread copies Rally's timing context into the thread, so the requests
    # sent from there belong to this operation.
    _, requests = await asyncio.to_thread(
        run, client, params["tier"], params["repo_id"]
    )
    es.on_request_end()
    return {"weight": 1, "unit": "ops", "success": True, "requests": requests}


def register(registry):
    registry.register_runner("layout-query", layout_query, async_runner=True)
