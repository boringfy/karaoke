"""Line-by-line lyric translation via an OpenAI-compatible chat endpoint.

Points at whatever local model the host is running (llama.cpp, vLLM, Ollama);
nothing is sent off the machine. Translation is opt-in per song and never part
of the automatic pipeline.

Alignment is the whole problem here: a translation list that slips by one
captions every line with its neighbour's meaning, which is worse than no
translation at all. So lines go out numbered, come back as a JSON array, and a
batch whose length does not match is rejected rather than patched up.
"""

from __future__ import annotations

import json
import logging

import httpx

log = logging.getLogger(__name__)

# Small batches keep the model's output short enough to stay well-formed, and
# limit the blast radius when one batch comes back malformed.
BATCH_SIZE = 20

_SYSTEM = (
    "You translate song lyrics. You are given a JSON array of lines. "
    "Return ONLY a JSON array of the same length, where element i is the "
    "translation of element i. Preserve order exactly. Do not merge, split, "
    "reorder, drop, or add lines. If a line has no meaningful content (an "
    "interjection, a vocalisation), return it unchanged. Output nothing but "
    "the JSON array."
)


class TranslationError(RuntimeError):
    pass


async def _one_batch(
    client: httpx.AsyncClient, url: str, model: str, lines: list[str], target: str
) -> list[str]:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": _SYSTEM},
            {
                "role": "user",
                "content": f"Translate into {target}.\n{json.dumps(lines, ensure_ascii=False)}",
            },
        ],
        "temperature": 0.2,
        "max_tokens": 4096,
        # Qwen-style reasoning models otherwise spend the whole budget in
        # reasoning_content and return empty content.
        "chat_template_kwargs": {"enable_thinking": False},
    }
    r = await client.post(url, json=payload)
    r.raise_for_status()
    content = (r.json()["choices"][0]["message"].get("content") or "").strip()
    if not content:
        raise TranslationError("model returned empty content")
    # Tolerate a ```json fence around the array.
    if content.startswith("```"):
        content = content.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        out = json.loads(content)
    except json.JSONDecodeError as e:
        raise TranslationError(f"model did not return JSON: {content[:120]}") from e
    if not isinstance(out, list) or len(out) != len(lines):
        raise TranslationError(
            f"expected {len(lines)} translations, got "
            f"{len(out) if isinstance(out, list) else type(out).__name__}"
        )
    return [str(x) if x is not None else "" for x in out]


async def translate_lines(
    lines: list[str], *, url: str, model: str, target: str = "English", timeout: float = 300.0
) -> list[str | None]:
    """Translate `lines`, returning one entry per input line.

    A batch that fails leaves its lines untranslated (None) rather than
    aborting the whole song: a partial translation is still useful, and the
    caller can retry.
    """
    out: list[str | None] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for i in range(0, len(lines), BATCH_SIZE):
            batch = lines[i : i + BATCH_SIZE]
            try:
                out.extend(await _one_batch(client, url, model, batch, target))
            except (httpx.HTTPError, TranslationError, KeyError, IndexError):
                log.exception("translation batch %d failed; leaving it blank", i // BATCH_SIZE)
                out.extend([None] * len(batch))
    return out
