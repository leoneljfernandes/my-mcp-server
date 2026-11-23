"""Strict Pydantic v2 domain models and custom exceptions."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

SourceName = Literal["superpowers", "modern-web-guidance", "my_skills"]
VALID_SOURCES: tuple[SourceName, ...] = ("superpowers", "modern-web-guidance", "my_skills")


class SkillRegistryError(Exception):
    """Base exception for skill registry errors."""


class PathTraversalError(SkillRegistryError):
    """Raised when a requested path escapes the configured skills root."""


class RoleNotFoundError(SkillRegistryError):
    """Raised when a requested role does not exist in roles.yaml."""


class SkillNotFoundError(SkillRegistryError):
    """Raised when a requested skill or web guide cannot be found."""


class InputValidationError(SkillRegistryError):
    """Raised when tool input violates safety or size constraints."""


class RoleConfig(BaseModel):
    """Declarative role entry inside config/roles.yaml."""

    description: str = ""
    instructions: str = ""
    core: list[str] = Field(default_factory=list)
    on_demand: list[str] = Field(default_factory=list)
    web_guidance: bool = False


class RolesFileConfig(BaseModel):
    """Root schema for config/roles.yaml."""

    precedence_rules: str = ""
    shared_on_demand: list[str] = Field(default_factory=list)
    roles: dict[str, RoleConfig] = Field(default_factory=dict)


class RoleSummary(BaseModel):
    """Structured output model for `list_roles`."""

    name: str = Field(description="Role identifier configured in roles.yaml")
    description: str = Field(description="Human-readable summary of the role")
    core_count: int = Field(description="Number of core skills always injected for this role")
    on_demand_count: int = Field(
        description="Number of on-demand skills cataloged for progressive loading"
    )
    core_tokens: int = Field(
        default=0, description="Estimated token cost of the role's core skills bundle"
    )
    missing_patterns: list[str] = Field(
        default_factory=list,
        description="Configured paths or globs that matched no files on disk",
    )


class SkillSummary(BaseModel):
    """Structured output model for `list_skills`."""

    source: SourceName = Field(description="Origin source of the skill")
    id: str = Field(description="Unique slug/identifier within the source")
    name: str = Field(description="Skill display or frontmatter name")
    relative_path: str = Field(description="POSIX path relative to skills_store")
    description: str = Field(description="Short description extracted from frontmatter or index")
    category: str | None = Field(default=None, description="Optional category folder")
    references: list[str] = Field(
        default_factory=list,
        description="Auxiliary reference Markdown files inside this skill (relative to source)",
    )
    token_estimate: int = Field(
        default=0, description="Estimated token cost of loading this skill (precomputed or chars/4)"
    )


class RoleIntegrityIssue(BaseModel):
    """A configuration problem found by `SkillRegistry.check_role_integrity`."""

    role: str = Field(description="Role where the issue was found")
    skill: str = Field(description="Skill id containing the reference (empty for missing patterns)")
    kind: Literal["missing_pattern", "unknown_reference", "unassigned_reference"]
    target: str = Field(description="Offending pattern or referenced superpowers skill id")


class SearchHit(BaseModel):
    """Structured output model for `search_skills`."""

    source: SourceName = Field(description="Origin source of the matching document")
    id: str = Field(description="Skill or guide identifier")
    name: str = Field(description="Document name")
    relative_path: str = Field(description="POSIX path relative to skills_store")
    score: float = Field(description="BM25 relevance score (higher is more relevant)")
    snippet: str = Field(description="Contextual excerpt around matched keywords")


class WebGuideSummary(BaseModel):
    """Structured output model for `search_modern_web_guidance`."""

    id: str = Field(description="Modern Web Guidance guide ID for use with retrieve_modern_web_guidance")
    category: str = Field(description="Web platform category (e.g. css, forms, security)")
    description: str = Field(description="Summary of the guidance")
    features_used: list[str] = Field(
        default_factory=list,
        description="Web platform features covered by this guide",
    )
    token_count: int | None = Field(
        default=None,
        description="Approximate token length of the compiled guide",
    )
