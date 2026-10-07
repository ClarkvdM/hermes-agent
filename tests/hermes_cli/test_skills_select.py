"""Synthetic skill-selection contracts; no provider credentials or live calls."""
from pathlib import Path

import pytest


@pytest.mark.parametrize('scores,budget,expected,reached', [
    ([5.99, 4, 0], 6000, [], False),
    ([9, 9, 8], 6000, ['a', 'b'], True),
    ([8, 6, 1], 6000, ['a', 'b'], False),
    ([9, 8, 7], 0, [], False),
])
def test_selection_threshold_target_and_empty(scores, budget, expected, reached):
    from hermes_cli.skills_select import Skill, select_skills
    skills = [Skill(k, k, '', 'Guidance ' + k) for k in 'abc']
    result = select_skills(skills, {s.id: {'score': v, 'confidence': .5} for s, v in zip(skills, scores)}, token_budget=budget)
    assert [s['id'] for s in result['selected']] == expected
    assert result['target_reached'] is reached
    assert result['token_count'] <= budget


def test_budget_boundary_includes_wrappers_and_special_tokens():
    from hermes_cli.skills_select import Skill, select_skills
    skills = [Skill('a', 'a', '', '<|endoftext|>\n完整 guidance')]
    scores = {'a': {'score': 9, 'confidence': 1}}
    full = select_skills(skills, scores)
    assert select_skills(skills, scores, token_budget=full['token_count'])['selected']
    assert not select_skills(skills, scores, token_budget=full['token_count'] - 1)['selected']
    assert skills[0].content in full['context']


def test_duplicate_names_with_different_contents_fail(tmp_path):
    from hermes_cli.skills_select import discover_skills
    for name in ['a', 'b']:
        path = tmp_path / name / 'SKILL.md'
        path.parent.mkdir()
        path.write_text('---\nname: collision\ndescription: Useful\n---\n' + name, encoding='utf-8')
    with pytest.raises(ValueError, match='Duplicate skill name'):
        discover_skills(tmp_path)


@pytest.mark.platforms('posix')
def test_symlinks_cannot_escape_root(tmp_path):
    from hermes_cli.skills_select import discover_skills
    root = tmp_path / 'skills'
    root.mkdir()
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'SKILL.md').write_text('---\nname: outside\ndescription: Forbidden\n---\nsecret', encoding='utf-8')
    (root / 'dir').symlink_to(outside, target_is_directory=True)
    (root / 'SKILL.md').symlink_to(outside / 'SKILL.md')
    skills, skipped = discover_skills(root)
    assert skills == []
    assert skipped[0]['reason'] == 'escaped_symlink'


@pytest.mark.parametrize('frontmatter', ['name: x', '---\nname: [\n---', '---\nname: x\n---', '---\n- x\n---'])
def test_invalid_frontmatter_fails(tmp_path, frontmatter):
    from hermes_cli.skills_select import discover_skills
    (tmp_path / 'SKILL.md').write_text(frontmatter, encoding='utf-8')
    with pytest.raises(ValueError):
        discover_skills(tmp_path)



def test_selection_skips_oversized_and_counts_complete_rendering():
    from hermes_cli.skills_select import Skill, select_skills, render_context
    skills = [Skill('a', 'large', '', 'huge ' * 3000),
              Skill('b', 'small', '', 'Useful short guidance.'),
              Skill('c', 'other', '', 'Other guidance.')]
    scores = {s.id: {'score': v, 'confidence': .9} for s, v in zip(skills, [9, 8.2, 6.5])}
    result = select_skills(skills, scores, token_budget=100, target=8)
    assert [s['id'] for s in result['selected']] == ['b']
    assert result['total_score'] == 8.2
    assert result['target_reached'] is True
    assert [s['reason'] for s in result['skipped']] == ['token_budget', 'target_reached']
    import tiktoken
    text = render_context([skills[1]])
    assert result['token_count'] == len(tiktoken.get_encoding('cl100k_base').encode(text))
    assert result['tokenizer'] == 'tiktoken:cl100k_base'



def test_discovery_parses_yaml_and_deduplicates_exact_files(tmp_path):
    from hermes_cli.skills_select import discover_skills

    text = '---\nname: sample\ndescription: >-\n  Useful: detailed\n  guidance.\n---\nFull instructions.\n'
    for folder in ['category/sample', 'copy', '.hidden/sample', 'archive/sample']:
        path = tmp_path / folder / 'SKILL.md'
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding='utf-8')
    skills, skipped = discover_skills(tmp_path)
    assert len(skills) == 1
    assert skills[0].description == 'Useful: detailed guidance.'
    assert skills[0].content == text
    assert [s['reason'] for s in skipped] == ['duplicate_content']
