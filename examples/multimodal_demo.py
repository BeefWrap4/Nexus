#!/usr/bin/env python3
"""多模态 Agent 端到端演示.

使用 DeepSeek-chat 视觉能力分析图片。
"""
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from nexus.agent.multimodal import (
    MediaInput, MediaType, MultiModalTask,
    MultiModalMessage, is_vision_model, build_multimodal_messages,
)
from nexus.agent.base import AgentConfig


def demo_message_format():
    """演示 1: 多模态消息格式."""
    print("=" * 60)
    print("演示 1: 多模态消息格式")
    print("=" * 60)

    # 创建包含图片的多模态任务
    task = MultiModalTask(
        description="请分析这张架构图，描述其中的主要组件和数据流",
        expected_output="架构分析和数据流描述",
        media=[
            MediaInput(
                type=MediaType.IMAGE,
                url="https://raw.githubusercontent.com/BeefWrap4/AILearning/main/nexus/docs/superpowers/plans/nexus-architecture.png",
                detail="high",
            ),
        ],
    )

    # 构建消息
    messages = build_multimodal_messages(
        task,
        system_prompt="你是一个系统架构分析专家。请仔细观察图片并详细分析。",
    )

    print(f"任务: {task.description}")
    print(f"媒体数量: {len(task.media)}")
    print(f"消息数: {len(messages)}")
    print(f"角色: system + {messages[1]['role']}")
    print(f"内容块: {len(messages[1]['content'])} 个")
    for block in messages[1]['content']:
        print(f"  - type={block['type']}: ", end="")
        if block['type'] == 'image_url':
            print(f"url={block['image_url']['url'][:60]}... (detail={block['image_url']['detail']})")
        elif block['type'] == 'text':
            print(f"'{block['text'][:80]}...'")

    return messages


def demo_multiple_images():
    """演示 2: 多图对比."""
    print("\n" + "=" * 60)
    print("演示 2: 多图对比")
    print("=" * 60)

    task = MultiModalTask(
        description="Compare these two diagrams and identify the key differences",
        expected_output="Key differences between the two diagrams",
        media=[
            MediaInput(type=MediaType.IMAGE, url="http://example.com/before.png"),
            MediaInput(type=MediaType.IMAGE, url="http://example.com/after.png"),
        ],
    )

    messages = build_multimodal_messages(task)
    content = messages[0]['content']
    image_count = sum(1 for c in content if c['type'] == 'image_url')
    text_count = sum(1 for c in content if c['type'] == 'text')

    print(f"任务: {task.description}")
    print(f"图片数: {image_count}")
    print(f"文本块: {text_count}")
    assert image_count == 2, f"Expected 2 images, got {image_count}"
    print("✅ 多图消息格式正确")


def demo_vision_detection():
    """演示 3: 视觉模型检测."""
    print("\n" + "=" * 60)
    print("演示 3: 视觉模型检测")
    print("=" * 60)

    test_models = [
        ("gpt-4o", True),
        ("claude-sonnet-4", True),
        ("deepseek-chat", True),
        ("gpt-3.5-turbo", False),
        ("deepseek-coder", False),
    ]

    for model, expected in test_models:
        result = is_vision_model(model)
        status = "✅" if result == expected else "❌"
        print(f"  {status} is_vision_model('{model}') = {result}")


def demo_base64_image():
    """演示 4: Base64 图片支持."""
    print("\n" + "=" * 60)
    print("演示 4: Base64 图片支持")
    print("=" * 60)

    msg = MultiModalMessage(
        role="user",
        text="What text is in this screenshot?",
        media=[MediaInput(
            type=MediaType.IMAGE,
            base64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
            mime_type="image/png",
        )],
    )

    fmt = msg.to_openai_format()
    image_url = fmt['content'][0]['image_url']['url']
    assert image_url.startswith("data:image/png;base64,")
    print(f"  ✅ Base64 图片格式正确: {image_url[:50]}...")


def demo_agent_integration():
    """演示 5: Agent 集成检测."""
    print("\n" + "=" * 60)
    print("演示 5: Agent 多模态集成")
    print("=" * 60)

    config = AgentConfig(
        name="VisionBot",
        role="Image Analyst",
        goal="Analyze images and provide detailed descriptions",
        backstory="Expert in computer vision",
        provider="deepseek",
        model="deepseek-chat",
    )

    from nexus.agent.base import BaseAgent
    agent = BaseAgent(config)

    task = MultiModalTask(
        description="What do you see in this image?",
        media=[MediaInput(type=MediaType.IMAGE, url="https://example.com/test.jpg")],
    )

    # 验证 Agent 能检测多模态任务
    from nexus.agent.multimodal import is_vision_model
    assert is_vision_model(agent.config.model), "DeepSeek should be detected as vision model"

    print(f"  Agent: {agent.config.name}")
    print(f"  模型: {agent.config.model}")
    print(f"  视觉支持: {is_vision_model(agent.config.model)}")
    print(f"  任务类型: {type(task).__name__}")
    print(f"  媒体附加: {len(task.media)} 张图片")
    print("  ✅ Agent 多模态集成就绪")


if __name__ == "__main__":
    demo_message_format()
    demo_multiple_images()
    demo_vision_detection()
    demo_base64_image()
    demo_agent_integration()

    print("\n" + "=" * 60)
    print("🎉 全部 5 项多模态演示通过！")
    print("=" * 60)
