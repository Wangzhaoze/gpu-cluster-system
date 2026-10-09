import posixpath
import re
import unicodedata
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator

PROTECTED = {"PATH", "VIRTUAL_ENV", "HOME", "USER", "LOGNAME", "CUDA_VISIBLE_DEVICES"}


def clean_credential(value: str) -> str:
    # Input methods and pasting add characters nobody sees on screen: full-width
    # forms, zero-width marks, no-break or surrounding spaces.
    value = unicodedata.normalize("NFKC", value)
    return "".join(c for c in value if unicodedata.category(c) != "Cf").strip()


def validate_env(values: dict[str, str]) -> dict[str, str]:
    for key, value in values.items():
        if (
            not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", key)
            or key in PROTECTED
            or key.startswith(("LAB_", "NVIDIA_"))
        ):
            raise ValueError(f"保留或无效环境变量: {key}")
        if "\x00" in value or len(value) > 8192:
            raise ValueError("环境变量过长或包含空字符")
    return values


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(Input):
    username: str = Field(max_length=32)
    password: str = Field(max_length=200)

    @field_validator("username", mode="before")
    @classmethod
    def canonical_username(cls, value):
        # Usernames are created as lowercase ASCII; pasted/mobile input may vary.
        return clean_credential(value).lower() if isinstance(value, str) else value


class UserCreate(Input):
    username: str = Field(pattern=r"^[a-z][a-z0-9_]{2,31}$")
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=200)
    role: Literal["ADMIN", "MEMBER"] = "MEMBER"
    default_environment_id: str | None = None
    max_gpus: int = Field(default=5, ge=0, le=64)
    max_debug_hours: int = Field(default=8, ge=1, le=8)


class UserPatch(Input):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Literal["ADMIN", "MEMBER"] | None = None
    enabled: bool | None = None
    default_environment_id: str | None = None
    max_gpus: int | None = Field(default=None, ge=0, le=64)
    max_debug_hours: int | None = Field(default=None, ge=1, le=8)


class PasswordReset(Input):
    password: str = Field(min_length=12, max_length=200)


class PasswordChange(Input):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=12, max_length=200)


class GpuSelection(Input):
    gpu_indices: list[StrictInt] | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_gpu_selection(self):
        if self.gpu_indices is not None:
            if len(self.gpu_indices) != self.requested_gpus:
                raise ValueError("指定显卡数量必须与 GPU 数量一致")
            if len(set(self.gpu_indices)) != len(self.gpu_indices) or any(i < 0 or i >= 64 for i in self.gpu_indices):
                raise ValueError("显卡编号不可重复，且必须为 0 到 63 的整数")
        return self


class JobSpec(GpuSelection):
    environment_id: str | None = None
    requested_gpus: int = Field(default=1, ge=1, le=64)
    requested_cpus: int = Field(default=4, ge=1, le=32)
    requested_ram_mb: int = Field(default=4096, ge=256, le=65536)
    time_limit_seconds: int = Field(default=3600, ge=5, le=604800)
    command: str = Field(min_length=1, max_length=10000)
    workdir: str = Field(default="/workspace", max_length=500)
    env: dict[str, str] = Field(default_factory=dict)
    output_name: str = Field(default="run", pattern=r"^[A-Za-z0-9_-]{1,80}$")

    @field_validator("workdir")
    @classmethod
    def safe_workdir(cls, value: str) -> str:
        if "\x00" in value or "\\" in value or ".." in value.split("/"):
            raise ValueError("workdir 必须位于 /workspace")
        normalized = posixpath.normpath(value)
        if normalized != "/workspace" and not normalized.startswith("/workspace/"):
            raise ValueError("workdir 必须位于 /workspace")
        return normalized

    @field_validator("env")
    @classmethod
    def safe_env(cls, values):
        return validate_env(values)


class DebugSpec(GpuSelection):
    environment_id: str | None = None
    requested_gpus: int = Field(default=1, ge=1, le=64)
    requested_cpus: int = Field(default=4, ge=1, le=32)
    requested_ram_mb: int = Field(default=4096, ge=256, le=65536)
    time_limit_seconds: int = Field(default=1800, ge=5, le=28800)
    approval_reason: str = Field(default="", max_length=2000)


class ApprovalDecision(Input):
    note: str = Field(default="", max_length=2000)


class TrainingExtension(Input):
    extra_seconds: int = Field(ge=1, le=604800)


class EnvironmentCreate(Input):
    name: str = Field(min_length=1, max_length=100)
    image: str = Field(min_length=1, max_length=300)
    image_version: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=2000)


class EnvironmentPatch(Input):
    enabled: bool


class EnvSetting(Input):
    user_id: str | None = None
    key: str
    value: str
    is_secret: bool = False
    enabled: bool = True

    @field_validator("key")
    @classmethod
    def safe_key(cls, key):
        validate_env({key: ""})
        return key

    @field_validator("value")
    @classmethod
    def safe_value(cls, value):
        if "\x00" in value or len(value) > 8192:
            raise ValueError("无效环境变量值")
        return value


class WorkloadPatch(Input):
    requested_gpus: int | None = Field(default=None, ge=1, le=64)
    gpu_indices: list[StrictInt] | None = Field(default=None, max_length=64)
    requested_cpus: int | None = Field(default=None, ge=1, le=32)
    requested_ram_mb: int | None = Field(default=None, ge=256, le=65536)
    time_limit_seconds: int | None = Field(default=None, ge=5, le=604800)
    command: str | None = Field(default=None, min_length=1, max_length=10000)
    workdir: str | None = Field(default=None, max_length=500)
    output_name: str | None = Field(default=None, pattern=r"^[A-Za-z0-9_-]{1,80}$")

    @model_validator(mode="after")
    def nonempty_patch(self):
        if not self.model_fields_set or any(getattr(self, key) is None for key in self.model_fields_set - {"gpu_indices"}):
            raise ValueError("请提供有效的修改字段")
        return self


class AnnouncementDraft(Input):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)

    @field_validator("title", "body")
    @classmethod
    def meaningful_text(cls, value):
        if not value.strip() or "\x00" in value:
            raise ValueError("公告标题和内容不能为空或包含空字符")
        return value.strip()
