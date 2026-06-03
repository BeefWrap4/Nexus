#!/usr/bin/env python3
"""Seed the default code review prompt template into NEXUS.

Usage:
    python scripts/seed_code_review_prompt.py

Creates:
    - PromptTemplate: name="code-review-standard", type="system"
    - PromptTemplateVersion: v1 with Jinja2 template content
"""

from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path
from uuid import UUID, uuid4

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv

env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)

from nexus.db.database import AsyncSessionLocal, close_db, init_db
from nexus.models.prompt import PromptTemplate, PromptTemplateVersion

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# Default tenant ID used by seed_data.py (default tenant)
DEFAULT_TENANT_ID = UUID("00000000-0000-0000-0000-000000000000")

CODE_REVIEW_TEMPLATE = """You are a {{ role }}. Review the following {{ language }} code with focus on {{ focus_areas }}.

{% if strictness == "strict" %}
Apply the highest code review standards. Flag every potential issue including minor style concerns.
{% elif strictness == "normal" %}
Balance thoroughness with practicality. Focus on bugs, security, and maintainability.
{% else %}
Only flag critical issues: security vulnerabilities and bugs that would cause runtime errors.
{% endif %}

## Code to Review
```{{ language }}
{{ diff_content }}
```

## Review Instructions
1. First use the available tools to detect issues (parse_diff, security_check, perf_check, style_check)
2. Then use your expertise to identify logic errors and design problems the tools cannot detect
3. Output findings in the structured JSON format below

## Output Format
Respond with a JSON object:
{
  "findings": [
    {
      "severity": "critical|warning|suggestion",
      "category": "security|performance|style|logic|maintainability",
      "file": "path/to/file",
      "line": 42,
      "title": "Short finding title",
      "description": "Detailed description of the issue",
      "suggestion": "Fix suggestion with example code if applicable"
    }
  ],
  "summary": {
    "overall_score": "1-10",
    "strengths": ["strength 1", "strength 2"],
    "risks": ["risk 1", "risk 2"],
    "review_notes": "Overall assessment summary"
  }
}
"""


async def seed_code_review_prompt() -> PromptTemplate:
    """Create the default code review prompt template."""
    async with AsyncSessionLocal() as session:
        # Check if template already exists
        from sqlalchemy import select

        existing = await session.execute(
            select(PromptTemplate).where(PromptTemplate.name == "code-review-standard")
        )
        if existing.scalar_one_or_none():
            logger.info("Prompt template 'code-review-standard' already exists. Skipping.")
            return existing.scalar_one_or_none()

        template = PromptTemplate(
            id=uuid4(),
            tenant_id=DEFAULT_TENANT_ID,
            name="code-review-standard",
            description="Default code review standard template with configurable strictness",
            template_type="system",
            current_version=1,
        )
        session.add(template)
        await session.flush()

        version = PromptTemplateVersion(
            id=uuid4(),
            template_id=template.id,
            version=1,
            content=CODE_REVIEW_TEMPLATE,
            variables=["role", "language", "focus_areas", "strictness", "diff_content"],
            change_notes="Initial code review template for Phase 8.1",
        )
        session.add(version)
        await session.commit()

        logger.info(f"Created prompt template: {template.name} (id={template.id})")
        return template


async def main():
    logger.info("Ensuring database tables exist...")
    await init_db()

    try:
        template = await seed_code_review_prompt()
        logger.info(f"Template ID: {template.id}")
        logger.info("Code review prompt template seeded successfully.")
    except Exception as exc:
        logger.error(f"Seeding failed: {exc}")
        raise SystemExit(1)
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
