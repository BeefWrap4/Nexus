import pytest
from nexus.agent.multimodal import (
    MediaInput, MediaType, MultiModalMessage, MultiModalTask,
    is_vision_model, build_multimodal_messages,
)


class TestMediaInput:
    def test_image_input(self):
        img = MediaInput(type=MediaType.IMAGE, url="https://example.com/photo.jpg")
        assert img.type == "image"
        assert img.mime_type == "image/png"

    def test_base64_input(self):
        img = MediaInput(type=MediaType.IMAGE, base64="abc123", mime_type="image/jpeg")
        assert img.url is None


class TestMultiModalMessage:
    def test_text_only_message(self):
        msg = MultiModalMessage(role="user", text="Hello")
        fmt = msg.to_openai_format()
        assert fmt["role"] == "user"
        assert fmt["content"][0]["type"] == "text"

    def test_image_message(self):
        msg = MultiModalMessage(role="user", text="What is this?",
            media=[MediaInput(type=MediaType.IMAGE, url="http://img.jpg")])
        fmt = msg.to_openai_format()
        assert len(fmt["content"]) == 2
        assert fmt["content"][0]["type"] == "image_url"
        assert fmt["content"][1]["type"] == "text"

    def test_base64_image_message(self):
        msg = MultiModalMessage(role="user", text="Analyze",
            media=[MediaInput(type=MediaType.IMAGE, base64="ZZZ", mime_type="image/png")])
        fmt = msg.to_openai_format()
        assert "base64,ZZZ" in fmt["content"][0]["image_url"]["url"]


class TestMultiModalTask:
    def test_task_with_media(self):
        task = MultiModalTask(
            description="Analyze this chart",
            media=[MediaInput(type=MediaType.IMAGE, url="http://chart.png")]
        )
        assert len(task.media) == 1
        assert task.text == "Analyze this chart"


class TestVisionDetection:
    @pytest.mark.parametrize("model,expected", [
        ("gpt-4o", True), ("deepseek-chat", True), ("claude-sonnet-4", True),
        ("gpt-3.5-turbo", False), ("deepseek-coder", False),
    ])
    def test_is_vision_model(self, model, expected):
        assert is_vision_model(model) == expected


class TestBuildMessages:
    def test_multimodal_messages(self):
        task = MultiModalTask(
            description="What is this image?",
            media=[MediaInput(type=MediaType.IMAGE, url="http://test.jpg")],
        )
        messages = build_multimodal_messages(task, system_prompt="You are helpful")
        assert len(messages) == 2  # system + user
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_multiple_images(self):
        task = MultiModalTask(
            description="Compare these",
            media=[
                MediaInput(type=MediaType.IMAGE, url="http://a.jpg"),
                MediaInput(type=MediaType.IMAGE, url="http://b.jpg"),
            ],
        )
        messages = build_multimodal_messages(task)
        content = messages[0]["content"]
        assert sum(1 for c in content if c["type"] == "image_url") == 2
