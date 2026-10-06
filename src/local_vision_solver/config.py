from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
import tomllib

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InferenceConfig(StrictModel):
    endpoint: str = "http://127.0.0.1:8081"
    model_alias: str = "qwen3-vl-local"
    timeout_seconds: float = Field(default=300, gt=0)
    initial_output_tokens: int = Field(default=4096, ge=256)
    maximum_output_tokens: int = Field(default=8192, ge=256)
    temperature: float = Field(default=0.1, ge=0, le=2)

    @field_validator("endpoint")
    @classmethod
    def loopback_only(cls, value: str) -> str:
        url = urlparse(value)
        if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "::1"}
                or url.username or url.password or url.query or url.fragment
                or url.path not in {"", "/"}):
            raise ValueError("Inference must use a literal loopback HTTP address")
        return value.rstrip("/")


class RuntimeConfig(StrictModel):
    executable: Path = Path("runtime/llama/llama-server.exe")
    model: Path = Path("models/Qwen3VL-8B-Instruct-Q4_K_M.gguf")
    projector: Path = Path("models/mmproj-Qwen3VL-8B-Instruct-F16.gguf")
    gpu_layers: int | Literal["auto"] = "auto"
    projector_on_gpu: bool = True
    context_size: int = Field(default=16384, ge=2048)
    batch_size: int = Field(default=512, ge=32)
    micro_batch_size: int = Field(default=128, ge=16)
    flash_attention: Literal["on", "off", "auto"] = "on"
    kv_cache_type: Literal["f16", "q8_0"] = "q8_0"
    vram_margin_megabytes: int = Field(default=1024, ge=256)

    @field_validator("gpu_layers")
    @classmethod
    def positive_layers(cls, value: int | str) -> int | str:
        if isinstance(value, int) and value < 0:
            raise ValueError("gpu_layers must be nonnegative or auto")
        return value


class PipelineConfig(StrictModel):
    session_directory: Path = Path("sessions")
    max_pages: int = Field(default=12, ge=1, le=100)
    max_input_megabytes: int = Field(default=300, ge=1)
    max_reading_retries: int = Field(default=1, ge=0, le=3)
    max_corrections: int = Field(default=1, ge=0, le=3)
    latency_target_seconds: float = Field(default=60, gt=0)


class RenderConfig(StrictModel):
    width: int = Field(default=832, ge=240, le=4096)
    height: int = Field(default=992, ge=240, le=4096)
    font_size: int = Field(default=48, ge=16)
    minimum_math_font_size: int = Field(default=34, ge=16)
    margin: int = Field(default=28, ge=8)
    font_path: Path = Path("C:/Windows/Fonts/segoeui.ttf")
    code_font_path: Path = Path("C:/Windows/Fonts/consola.ttf")
    math_engine: Literal["mathtext", "tex"] = "mathtext"


class ServerConfig(StrictModel):
    host: str = "0.0.0.0"
    port: int = Field(default=8765, ge=1024, le=65535)
    advertise: bool = True
    service_name: str = "Local Vision Solver"
    advertise_address: str | None = None
    max_queued_jobs: int = Field(default=8, ge=1, le=100)
    max_page_megabytes: int = Field(default=60, ge=1, le=300)
    retain_sessions: bool = True
    retention_hours: int = Field(default=24, ge=1)


class Config(StrictModel):
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def load_config(path: Path) -> Config:
    path = path.resolve()
    with path.open("rb") as handle:
        config = Config.model_validate(tomllib.load(handle))
    for obj, names in ((config.runtime, ("executable", "model", "projector")),
                       (config.pipeline, ("session_directory",)),
                       (config.render, ("font_path", "code_font_path"))):
        for name in names:
            value = getattr(obj, name)
            if not value.is_absolute():
                setattr(obj, name, (path.parent / value).resolve())
    if config.inference.maximum_output_tokens < config.inference.initial_output_tokens:
        raise ValueError("maximum_output_tokens must be >= initial_output_tokens")
    if config.render.width <= config.render.margin * 2 + config.render.font_size:
        raise ValueError("Card width leaves no readable content area")
    return config
