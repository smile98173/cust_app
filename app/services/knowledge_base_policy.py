from collections.abc import Collection, Mapping
from typing import Optional


LEGACY_COMMON_KNOWLEDGE_BASE = "通用"
CENTRAL_COMMON_KNOWLEDGE_BASE = "通用-中區"
JIANNAN_COMMON_KNOWLEDGE_BASE = "通用-嘉南區"

REGIONAL_COMMON_KNOWLEDGE_BASES = (
    CENTRAL_COMMON_KNOWLEDGE_BASE,
    JIANNAN_COMMON_KNOWLEDGE_BASE,
)

# Kept for compatibility with callers that import the old policy constant.
# Regional common knowledge bases are now assignable to supervisors.
SUPERVISOR_READ_ONLY_KNOWLEDGE_BASES = frozenset()

KNOWLEDGE_BASE_ALIASES = {
    "台灣佳光": "西海岸",
}

REGIONAL_COMMON_MEMBERS = {
    CENTRAL_COMMON_KNOWLEDGE_BASE: frozenset(
        ("大屯", "西海岸", "佳光市區", "中投", "佳聯", "北港")
    ),
    JIANNAN_COMMON_KNOWLEDGE_BASE: frozenset(("大揚", "新永安")),
}


def normalize_knowledge_base_name(value: str) -> str:
    name = str(value or "").strip()
    if name == LEGACY_COMMON_KNOWLEDGE_BASE:
        return CENTRAL_COMMON_KNOWLEDGE_BASE
    return KNOWLEDGE_BASE_ALIASES.get(name, name)


def regional_common_knowledge_base(
    knowledge_base: str,
    common_members: Mapping[str, Collection[str]] | None = None,
) -> Optional[str]:
    matches = regional_common_knowledge_bases(knowledge_base, common_members)
    return matches[0] if len(matches) == 1 else None


def regional_common_knowledge_bases(
    knowledge_base: str,
    common_members: Mapping[str, Collection[str]] | None = None,
) -> list[str]:
    target = normalize_knowledge_base_name(knowledge_base)
    members_by_common = (
        REGIONAL_COMMON_MEMBERS
        if common_members is None
        else common_members
    )
    matches = []
    for common_base in REGIONAL_COMMON_KNOWLEDGE_BASES:
        members = members_by_common.get(common_base, ())
        normalized_members = {
            normalize_knowledge_base_name(member)
            for member in members
        }
        if target in normalized_members:
            matches.append(common_base)
    return matches


def retrieval_common_knowledge_bases(
    knowledge_base: str,
    common_members: Mapping[str, Collection[str]] | None = None,
) -> list[str]:
    raw_target = str(knowledge_base or "").strip()
    if raw_target == LEGACY_COMMON_KNOWLEDGE_BASE:
        return [
            CENTRAL_COMMON_KNOWLEDGE_BASE,
            LEGACY_COMMON_KNOWLEDGE_BASE,
        ]

    target = normalize_knowledge_base_name(raw_target)
    if target == CENTRAL_COMMON_KNOWLEDGE_BASE:
        return [CENTRAL_COMMON_KNOWLEDGE_BASE, LEGACY_COMMON_KNOWLEDGE_BASE]
    if target == JIANNAN_COMMON_KNOWLEDGE_BASE:
        return [JIANNAN_COMMON_KNOWLEDGE_BASE]

    matches = regional_common_knowledge_bases(target, common_members)
    if len(matches) > 1:
        return []

    bases = []
    for regional_base in matches:
        bases.append(regional_base)
        if regional_base == CENTRAL_COMMON_KNOWLEDGE_BASE:
            bases.append(LEGACY_COMMON_KNOWLEDGE_BASE)
    return bases
