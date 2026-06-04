"""Multi-modal Agent support — images, audio, video."""

from dataclasses import dataclass, field
from typing import Any


class MediaType:
    IMAGE = "image"
    AUDIO = "audio"
    VIDEO = "video"


@dataclass
class MediaInput:
    """媒体输入（图像/音频/视频）."""
    type: str  # "image" | "audio" | "video"
    url: str | None = None          # 远程 URL
    base64: str | None = None       # base64 编码数据
    mime_type: str = "image/png"    # MIME 类型
    detail: str = "auto"            # 图像分辨率: low/high/auto


@dataclass
class MultiModalMessage:
    """多模态消息 — 文本 + 媒体."""
    role: str = "user"
    text: str = ""
    media: list[MediaInput] = field(default_factory=list)

    def to_openai_format(self) -> dict:
        """转换为 OpenAI Vision API 格式."""
        content = []
        for m in self.media:
            if m.type == MediaType.IMAGE:
                image_url = m.url or f"data:{m.mime_type};base64,{m.base64}"
                content.append({
                    "type": "image_url",
                    "image_url": {"url": image_url, "detail": m.detail},
                })
            elif m.type == MediaType.AUDIO:
                content.append({
                    "type": "input_audio",
                    "input_audio": {"data": m.base64, "format": m.mime_type.split("/")[-1]},
                })
        if self.text:
            content.append({"type": "text", "text": self.text})
        return {"role": self.role, "content": content}


@dataclass
class MultiModalTask:
    """多模态任务."""
    description: str
    expected_output: str = ""
    context: dict[str, Any] = field(default_factory=dict)
    media: list[MediaInput] = field(default_factory=list)
    # 向后兼容
    @property
    def text(self) -> str:
        return self.description


def is_vision_model(model: str) -> bool:
    """判断模型是否支持视觉."""
    vision_models = {
        "gpt-4o", "gpt-4-turbo", "gpt-4-vision",
        "claude-3", "claude-sonnet-4", "claude-opus-4",
        "gemini-pro-vision", "gemini-flash",
        "deepseek-vl2", "deepseek-chat",
        "qwen-vl", "qwen2.5-vl",
    }
    return any(vm in model.lower() for vm in vision_models)


def build_multimodal_messages(
    task: MultiModalTask,
    system_prompt: str = "",
    include_memory: list[dict] | None = None,
) -> list[dict]:
    """构建多模态消息列表."""
    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if include_memory:
        messages.extend(include_memory)

    msg = MultiModalMessage(role="user", text=task.description, media=task.media)
    messages.append(msg.to_openai_format())
    return messages
