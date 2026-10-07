from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
import tomllib

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .app_paths import AppPaths


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
        if not url.port or not 1024 <= url.port <= 65535:
            raise ValueError("Inference requires an explicit port in 1024..65535")
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
    max_prepared_megabytes: int = Field(default=512, ge=1)


class RenderConfig(StrictModel):
    width: int = Field(default=832, ge=240, le=4096)
    height: int = Field(default=992, ge=240, le=4096)
    font_size: int = Field(default=48, ge=16)
    minimum_math_font_size: int = Field(default=34, ge=16)
    margin: int = Field(default=28, ge=8)
    font_path: Path = Path("C:/Windows/Fonts/segoeui.ttf")
    code_font_path: Path = Path("C:/Windows/Fonts/consola.ttf")
    math_engine: Literal["mathtext"] = "mathtext"

    @model_validator(mode="after")
    def readable_area(self):
        if self.minimum_math_font_size > self.font_size:
            raise ValueError("minimum_math_font_size must be <= font_size")
        if self.width <= 2 * self.margin + self.font_size:
            raise ValueError("Card width leaves no readable content area")
        if self.height <= 2 * self.margin + 52 + int(self.font_size * 1.35):
            raise ValueError("Card height leaves no readable content area")
        return self


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
    cleanup_interval_seconds: int = Field(default=60, ge=1)
    receiving_idle_timeout_seconds: int = Field(default=3600, ge=1)
    max_active_sessions: int = Field(default=32, ge=1)
    max_image_pixels: int = Field(default=64_000_000, ge=25600)
    max_uploads: int = Field(default=4, ge=1, le=16)
    max_previews: int = Field(default=2, ge=1, le=8)
    preview_slot_timeout_seconds: float = Field(default=2, gt=0)
    upload_idle_timeout_seconds: float = Field(default=30, gt=0)
    upload_timeout_seconds: float = Field(default=180, gt=0)
    preview_timeout_seconds: float = Field(default=60, gt=0)
    disk_reserve_megabytes: int = Field(default=2048, ge=0)


class Config(StrictModel):
    data_directory: Path | None = None
    inference: InferenceConfig = Field(default_factory=InferenceConfig)
    runtime: RuntimeConfig = Field(default_factory=RuntimeConfig)
    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    render: RenderConfig = Field(default_factory=RenderConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)

    @property
    def paths(self):
        return AppPaths((self.data_directory or self.pipeline.session_directory.resolve().parent).resolve())

    @model_validator(mode="after")
    def token_limits(self):
        if self.inference.maximum_output_tokens < self.inference.initial_output_tokens:
            raise ValueError("maximum_output_tokens must be >= initial_output_tokens")
        return self


def load_config(path: Path, data_dir: Path | None = None) -> Config:
    path = path.resolve()
    with path.open("rb") as handle:
        config = Config.model_validate(tomllib.load(handle))
    if config.data_directory is not None and not config.data_directory.is_absolute():
        config.data_directory=(path.parent/config.data_directory).resolve()
    for obj, names in ((config.runtime, ("executable", "model", "projector")),
                       (config.pipeline, ("session_directory",)),
                       (config.render, ("font_path", "code_font_path"))):
        for name in names:
            value = getattr(obj, name)
            if not value.is_absolute():
                setattr(obj, name, (path.parent / value).resolve())
    if data_dir is not None:
        paths = AppPaths.for_user(data_dir)
        config.data_directory = paths.data
        config.pipeline.session_directory = paths.sessions
        config.runtime.executable = paths.runtime / "llama-server.exe"
        config.runtime.model = paths.models / config.runtime.model.name
        config.runtime.projector = paths.models / config.runtime.projector.name
    return config


def product_config(paths: AppPaths):
    config = Config(data_directory=paths.data)
    config.pipeline.session_directory=paths.sessions
    config.runtime.executable=paths.runtime/'llama-server.exe'
    config.runtime.model=paths.models/config.runtime.model.name
    config.runtime.projector=paths.models/config.runtime.projector.name
    config.server.retain_sessions=False
    return config


def save_config(config:Config,path:Path):
    import json
    from .storage import write_bytes
    config = Config.model_validate(config.model_dump())
    data=config.model_dump(mode='json')
    lines=[]
    for key,value in data.items():
        if value is not None and not isinstance(value,dict):
            lines.append(key+' = '+json.dumps(value,ensure_ascii=False))
    for section,values in data.items():
        if not isinstance(values,dict):
            continue
        lines.append('\n['+section+']')
        for key,value in values.items():
            if value is not None:
                lines.append(key+' = '+json.dumps(value,ensure_ascii=False))
    path.parent.mkdir(parents=True,exist_ok=True)
    write_bytes(path,('\n'.join(lines)+'\n').encode('utf-8'))
