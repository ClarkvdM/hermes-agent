"""Opt-in skill selection. Skill bodies stay local; no agent-context integration."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    description: str
    content: str


class InvalidSkillError(ValueError):
    """A static reason safe to report without YAML source snippets."""

    def __init__(self, path: Path, reason: str, message: str):
        self.reason = reason
        super().__init__(f'{message}: {path}')


def _read_skill(path: Path) -> tuple[str, str, str]:
    # Preserve original bytes (including CRLF) for exact-content deduplication.
    content = path.read_bytes().decode('utf-8')
    lines = content.splitlines()
    if not lines or lines[0] != '---':
        raise InvalidSkillError(path, 'missing_frontmatter', 'Missing YAML frontmatter')
    try:
        end = next(i for i in range(1, len(lines)) if lines[i] == '---')
        metadata = YAML(typ='safe').load('\n'.join(lines[1:end]))
    except (StopIteration, YAMLError) as exc:
        raise InvalidSkillError(path, 'invalid_yaml', 'Invalid YAML frontmatter') from exc
    if not isinstance(metadata, dict):
        raise InvalidSkillError(path, 'invalid_metadata', 'Frontmatter must be a mapping')
    for field in ('name', 'description'):
        if not isinstance(metadata.get(field), str) or not metadata[field].strip():
            raise InvalidSkillError(path, f'missing_{field}', f'Frontmatter requires nonempty {field}')
    return metadata['name'], metadata['description'], content


def discover_skills(root: Path, *, skip_invalid: bool = False) -> tuple[list[Skill], list[dict]]:
    root = root.expanduser().resolve()
    if not root.is_dir():
        raise ValueError(f'Skills directory does not exist: {root}')
    skills, skipped, contents, names = [], [], {}, set()
    for directory, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = sorted(d for d in dirs if not d.startswith('.')
                         and d.casefold() not in {'archive', 'archives', 'archived'}
                         and not (Path(directory) / d).is_symlink())
        if 'SKILL.md' not in files:
            continue
        path = Path(directory) / 'SKILL.md'
        if not path.resolve().is_relative_to(root):
            skipped.append({'reason': 'escaped_symlink', 'path': str(path.relative_to(root))})
            continue
        try:
            name, description, content = _read_skill(path)
        except InvalidSkillError as exc:
            if not skip_invalid:
                raise
            skipped.append({'path': str(path.relative_to(root)), 'reason': exc.reason})
            continue
        if content in contents:
            skipped.append({'name': name, 'reason': 'duplicate_content', 'duplicate_of': contents[content]})
            continue
        if name in names:
            raise ValueError(f'Duplicate skill name with different content: {name}')
        skill_id = f'skill_{len(skills):05d}'
        contents[content] = skill_id
        names.add(name)
        skills.append(Skill(skill_id, name, description, content))
    return skills, skipped


def render_context(skills: list[Skill]) -> str:
    """Full SKILL.md documents, including frontmatter, with deterministic wrappers."""
    return ''.join(f'<skill id="{s.id}">\n{s.content}\n</skill>\n' for s in skills)


def context_tokenizer():
    try:
        import tiktoken
    except ImportError as exc:
        raise ValueError('Exact token counting requires the skills-select extra (hermes pm install --extra skills-select).') from exc
    return tiktoken.get_encoding('cl100k_base')


def select_skills(skills: list[Skill], scores: dict, *, minimum: float = 6,
                  target: float = 18, token_budget: int = 6000,
                  max_skills: int | None = None) -> dict:
    tokenizer = context_tokenizer()
    ranked = sorted(skills, key=lambda s: (-scores[s.id]['score'], s.name, s.id))
    selected, skipped, rows = [], [], []
    total_score, token_count = 0.0, 0
    for skill in ranked:
        row = {'id': skill.id, 'name': skill.name, **scores[skill.id]}
        rows.append(row)
        reason = None
        if row['score'] < minimum:
            reason = 'below_minimum'
        elif max_skills is not None and len(selected) >= max_skills:
            reason = 'max_skills'
        elif total_score >= target:
            reason = 'target_reached'
        else:
            count = len(tokenizer.encode(render_context(selected + [skill]), disallowed_special=()))
            if count > token_budget:
                reason = 'token_budget'
            else:
                selected.append(skill)
                total_score += row['score']
                token_count = count
        if reason:
            skipped.append({**row, 'reason': reason})
    selected_ids = {s.id for s in selected}
    return {'selected': [r for r in rows if r['id'] in selected_ids], 'ranked': rows,
            'skipped': skipped, 'total_score': total_score, 'token_count': token_count,
            'tokenizer': 'tiktoken:cl100k_base', 'token_budget': token_budget,
            'minimum_score': minimum, 'target_score': target, 'max_skills': max_skills,
            'target_reached': total_score >= target, 'selected_count': len(selected),
            'ranked_count': len(rows), 'context': render_context(selected)}
