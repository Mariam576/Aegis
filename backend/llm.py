"""Gemini API wrapper tuned for the free tier, plus a helper that returns parsed JSON."""
import asyncio
import json
import time

from google import genai
from google.genai import errors, types

import config

JSON_RULE = "Respond with one valid JSON object and nothing else."

_client = None
_slots = asyncio.Semaphore(config.GEMINI_CONCURRENCY)  # max requests in flight
_pacers: dict = {}


class _Pacer:
    """Spaces requests out so we stay under the free tier's requests-per-minute limit.
    Limits are counted per model, so each model gets its own pacer."""

    def __init__(self, rpm: int):
        self.interval = 60 / max(rpm, 1)
        self.next_slot = 0.0
        self.lock = asyncio.Lock()

    async def wait(self):
        async with self.lock:
            now = time.monotonic()
            delay = max(0.0, self.next_slot - now)
            self.next_slot = max(now, self.next_slot) + self.interval
        if delay:
            await asyncio.sleep(delay)


def _get_client() -> genai.Client:
    global _client
    if _client is None:
        if not config.GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not set. Get a free key in Google AI Studio "
                               "and add it to your .env file.")
        _client = genai.Client(
            api_key=config.GEMINI_API_KEY,
            http_options=types.HttpOptions(
                timeout=180_000,  # milliseconds
                # Retry "too many requests" (429) and temporary server errors, with backoff
                retry_options=types.HttpRetryOptions(
                    attempts=5, initial_delay=5.0, max_delay=60.0,
                    http_status_codes=[408, 429, 500, 502, 503, 504],
                ),
            ),
        )
    return _client


async def ask(prompt: str, *, system: str = "", model: str = config.MODEL_SMART,
              max_tokens: int = 8192, json_mode: bool = False) -> str:
    cfg = types.GenerateContentConfig(
        system_instruction=system or None,
        # Gemini's internal "thinking" can use part of this budget, so keep it generous
        max_output_tokens=max_tokens,
        response_mime_type="application/json" if json_mode else "text/plain",
    )
    if model not in _pacers:
        _pacers[model] = _Pacer(config.GEMINI_RPM)

    async with _slots:
        await _pacers[model].wait()
        try:
            resp = await _get_client().aio.models.generate_content(
                model=model, contents=prompt, config=cfg)
        except errors.ClientError as e:
            if e.code == 429:
                raise RuntimeError(
                    "Gemini free-tier limit reached. Wait a minute and try again (or tomorrow if "
                    "you used up the daily limit). Quick depth uses fewer requests.") from e
            if e.code == 404:
                raise RuntimeError(f"Gemini model '{model}' not found. Pick a current model "
                                   "in Google AI Studio and update .env.") from e
            raise

    text = (resp.text or "").strip()
    if not text:
        reason = resp.candidates[0].finish_reason if resp.candidates else "blocked"
        raise RuntimeError(f"Gemini returned an empty response ({reason}).")
    return text


def _parse(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object in model output")
    return json.loads(text[start:end + 1])


async def ask_json(prompt: str, *, system: str = "", model: str = config.MODEL_SMART,
                   max_tokens: int = 8192) -> dict:
    system = f"{system}\n\n{JSON_RULE}".strip()
    text = await ask(prompt, system=system, model=model, max_tokens=max_tokens, json_mode=True)
    try:
        return _parse(text)
    except ValueError:  # json.JSONDecodeError is a ValueError too -> one repair attempt
        repaired = await ask(f"Repair this into valid JSON. Output only the JSON.\n\n{text}",
                             system=JSON_RULE, model=config.MODEL_FAST,
                             max_tokens=max_tokens, json_mode=True)
        return _parse(repaired)
