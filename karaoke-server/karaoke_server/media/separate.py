"""Vocal/instrumental separation via audio-separator (UVR models).

Both presets use true 2-stem models that output Vocals + Instrumental
directly (no stem re-mixing needed):
  fast    -> UVR-MDX-NET Inst HQ3 (ONNX, quick even on CPU)
  quality -> BS-Roformer (best public SDR; slower, loves a GPU)
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..config import get_settings

log = logging.getLogger(__name__)


class SeparationUnavailable(RuntimeError):
    pass


def separate_track(src: Path, out_dir: Path) -> tuple[Path, Path]:
    """Blocking (call from a worker thread).

    Returns (vocals_wav, instrumental_wav) inside out_dir.
    """
    try:
        from audio_separator.separator import Separator
    except ImportError as e:
        raise SeparationUnavailable(
            "audio-separator not installed. Install ML extras: "
            "pip install 'karaoke-server[ml]'"
        ) from e

    settings = get_settings()
    separator = Separator(
        log_level=logging.WARNING,
        model_file_dir=str(settings.models_dir / "separation"),
        output_dir=str(out_dir),
        output_format="WAV",
    )
    separator.load_model(model_filename=settings.separation_model)

    try:
        outputs = separator.separate(
            str(src),
            custom_output_names={"Vocals": "vocals", "Instrumental": "instrumental"},
        )
    except TypeError:
        # Older audio-separator without custom_output_names.
        outputs = separator.separate(str(src))

    vocals = instrumental = None
    for name in outputs:
        p = Path(name)
        if not p.is_absolute():
            p = out_dir / p
        low = p.stem.lower()
        if "vocal" in low and "instrumental" not in low:
            vocals = p
        elif "instrumental" in low:
            instrumental = p
    if not vocals or not instrumental or not vocals.exists() or not instrumental.exists():
        raise RuntimeError(f"separation produced unexpected outputs: {outputs}")

    canonical_v = out_dir / "vocals.wav"
    canonical_i = out_dir / "instrumental.wav"
    if vocals != canonical_v:
        vocals.replace(canonical_v)
    if instrumental != canonical_i:
        instrumental.replace(canonical_i)
    return canonical_v, canonical_i
