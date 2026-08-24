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

# Deliberately small. A long list invites the model to get lazy — truncating,
# merging or splitting entries — and every one of those shows up as a length
# mismatch that costs the whole batch. Short prompts stay well-formed, and a
# failure only puts a handful of lines through the slower per-line path.
BATCH_SIZE = 5

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
        "max_tokens": 1024,
        # Qwen-style reasoning models otherwise spend the whole budget in
        # reasoning_content and return empty content.
        "chat_template_kwargs": {"enable_thinking": False},
        # Every call is a fresh translation of unrelated lines. Reusing the
        # server's KV cache across them buys nothing and risks the model
        # drifting toward whatever it saw last.
        "cache_prompt": False,
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
                continue
            except (httpx.HTTPError, TranslationError, KeyError, IndexError):
                log.warning(
                    "translation batch %d failed; retrying line by line", i // BATCH_SIZE
                )
            # Batches fail mainly because the model splits or merges a line and
            # returns the wrong count. Sending one line at a time makes that
            # impossible to get wrong: one input, one output, no alignment to
            # lose. Slower, so it is only the fallback.
            for line in batch:
                try:
                    out.extend(await _one_batch(client, url, model, [line], target))
                except (httpx.HTTPError, TranslationError, KeyError, IndexError):
                    log.warning("line translation failed; leaving it blank")
                    out.append(None)
    return out
