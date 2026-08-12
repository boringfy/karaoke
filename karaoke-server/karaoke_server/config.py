from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _default_data_dir() -> Path:
    return Path.home() / ".local" / "share" / "karaoke-server"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KARAOKE_", env_file=".env", extra="ignore")

    data_dir: Path = _default_data_dir()
    host: str = "127.0.0.1"
    port: int = 8787
    # Allowed CORS origins for the UI. Set KARAOKE_CORS_ORIGINS to a
    # comma-separated list, e.g. "http://localhost:5173,https://myui.local".
    # Use "*" to allow any origin (convenient for a purely local app).
    cors_origins: Annotated[list[str], NoDecode] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [item.strip() for item in v.split(",") if item.strip()]
        return v

    # Device for ML stages: "auto" picks cuda > mps > cpu.
    device: Literal["auto", "cpu", "cuda", "mps"] = "auto"

    # Abandon a pipeline stage that has run this long. Guards against a stage
    # wedging on a hung network call or model load and blocking the queue
    # forever. Generous: separation/alignment scale with track length.
    stage_timeout_sec: int = 3600

    # Whisper model used for forced alignment (stable-ts over faster-whisper).
    whisper_model: str = "large-v3-turbo"
    whisper_compute_type: str = "int8"

    # Separation preset. Both are true 2-stem (Vocals/Instrumental) models:
    # "fast" = UVR MDX-NET Inst HQ3, "quality" = BS-Roformer.
    separation_preset: Literal["fast", "quality"] = "fast"
    separation_model_fast: str = "UVR-MDX-NET-Inst_HQ_3.onnx"
    separation_model_quality: str = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"

    # Encode the instrumental to opus at this bitrate; empty string keeps WAV.
    instrumental_bitrate: str = "128k"
    keep_vocal_stem: bool = False

    # Lyrics providers. Scraping-based syncedlyrics providers (Musixmatch, ...)
    # are ToS-gray and breakage-prone, so they are opt-in.
    enable_scraping_providers: bool = False
    lyrics_search_limit: int = 3

    # Lines with mean word probability below this are marked "interpolated";
    # songs whose overall score is below song_review_threshold become needs_review.
    line_confidence_threshold: float = 0.45
    song_review_threshold: float = 0.55

    @property
    def db_path(self) -> Path:
        return self.data_dir / "karaoke.db"

    @property
    def songs_dir(self) -> Path:
        return self.data_dir / "songs"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"

    @property
    def separation_model(self) -> str:
        return (
            self.separation_model_fast
            if self.separation_preset == "fast"
            else self.separation_model_quality
        )

    def ensure_dirs(self) -> None:
        self.songs_dir.mkdir(parents=True, exist_ok=True)
        self.models_dir.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    return Settings()
