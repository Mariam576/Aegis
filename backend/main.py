"""FastAPI server: serves the website and streams the agent's progress (Server-Sent Events)."""
import asyncio
import json
import traceback

from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

import config
from agent import ResearchAgent

app = FastAPI(title="AI Research Agent")


def sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.get("/api/health")
def health():
    return {"llm_ready": bool(config.GEMINI_API_KEY),
            "search": "tavily" if config.TAVILY_API_KEY else "duckduckgo"}


@app.get("/api/research")
async def research(topic: str = Query(..., min_length=3, max_length=300),
                   depth: str = Query("standard", pattern="^(quick|standard|deep)$")):
    queue: asyncio.Queue = asyncio.Queue()

    async def worker():
        try:
            async for event, data in ResearchAgent(topic, depth).run():
                await queue.put(sse(event, data))
        except Exception as e:
            traceback.print_exc()
            await queue.put(sse("failed", {"message": str(e)}))
        finally:
            await queue.put(None)  # tells the stream we're finished

    async def stream():
        task = asyncio.create_task(worker())
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=15)
                except asyncio.TimeoutError:
                    yield ": keep-alive\n\n"  # stops proxies closing a quiet connection
                    continue
                if item is None:
                    break
                yield item
            yield sse("done", {})
        finally:
            task.cancel()  # user closed the tab -> stop the agent

    return StreamingResponse(stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# The website. Mounted last so it doesn't shadow the /api routes.
app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="site")
