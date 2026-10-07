# Select skills with Jev

`hermes skills select` scores installed skill descriptions against a task and returns useful guidance within a token budget. It is a standalone CLI command. It does not change the agent's system prompt, load skills into a conversation, or modify installed skills.

## Preview before uploading

```bash
hermes skills select "Review this software change" --dry-run
hermes skills select -p "Review this software change" --skills-dir ./skills --dry-run
printf '%s' 'Review this software change' | hermes skills select - --dry-run
```

The default root is the active profile's `skills` directory. Put global profile flags **before** `skills select`, for example `hermes --profile work skills select -p "Review a change" --dry-run`. After `select`, `-p` means `--prompt`.

`--dry-run` prints the exact JSON request payloads without reading a key, loading a tokenizer, or making network requests. It does not predict scores. The endpoint, candidate count, batch count and discovery skips accompany the payloads. Dry runs require the default JSON format.

To try the synthetic fixtures from a source checkout:

```bash
python -m hermes_cli.main skills select "Review a software change" \
  --skills-dir tests/fixtures/skills_select --dry-run
```

## Score and select

Exact local token counting uses `tiktoken` with `cl100k_base`, also used by repository evaluation tools. The core runtime only has rough estimates, so this command has a pinned optional dependency:

```bash
hermes pm install --extra skills-select
```

The tokenizer downloads its public encoding table on first use if it is not already cached. This download contains no task or skill data. To prepare the cache before scoring, run the following with the interpreter that runs Hermes:

```bash
python -c 'import tiktoken; tiktoken.get_encoding("cl100k_base")'
```

Set `TYPESAFE_API_KEY` in the process environment through your usual secret-injection mechanism. The command does not read `.env` files, profile credentials, or key files. Do not put the key in a CLI argument.

```bash
hermes skills select "Review this software change" --allow-upload
hermes skills select --prompt "Review this software change" \
  --context-file ./recent-context.txt --allow-upload --format context
hermes skills select "Review this software change" --allow-upload \
  --minimum-score 6 --target-score 18 --token-budget 6000
hermes skills select "Review the skill-selection CLI for correctness and security" \
  --allow-upload --skip-invalid --max-skills 1 --token-budget 16000
```

`--context-file` reads UTF-8 text. The task can be positional or `--prompt`/`-p`, not both. Use `-` with either form to read the task from stdin.

## Selection rules

Each skill receives an independent 0–9 score for useful, applicable guidance rather than topic overlap. The provider returns a probability-weighted score, so decimal values are preserved. Confidence is reported but does not alter ranking.

1. Sort by descending score, then name and ID for deterministic ties.
2. Reject scores below `--minimum-score` (default 6, inclusive).
3. Add whole skills until their cumulative score reaches `--target-score` (default 18).
4. Never exceed `--token-budget` (default 6000). Skip a skill that will not fit and continue considering smaller skills.
5. Stop adding skills at `--max-skills` when supplied (positive integer; default unlimited). `--max-skills 1` selects the highest-ranked qualifying skill that fits, independently of the cumulative target. A rejected oversized skill does not consume the cap.

The target is a stopping point, not a quota. A result may fall short or contain no skills. No skill is truncated. Only byte-identical SKILL.md content is deduplicated; related skills still receive independent scores.

The hard token ceiling counts the **complete rendered guidance**, including YAML frontmatter, `<skill>` wrappers, and separators. It does not count the task, recent context, JSON reporting fields, or any future agent prompt. `cl100k_base` is not the Jev tokenizer or a guarantee about another model's token count.

## Output

JSON is the default. It includes:

- `selected`, `ranked`, and `skipped`, with score and confidence for scored candidates;
- skip reasons (`below_minimum`, `max_skills`, `target_reached`, `token_budget`, `duplicate_content`, or `escaped_symlink`), plus invalid-frontmatter reasons when explicitly allowed;
- `total_score`, `target_reached`, `token_count`, `tokenizer`, configured limits and counts;
- the full rendered `context`, pinned `model`, batch count and summed provider `usage`.

`--format context` writes only the selected documents and wrappers. An empty selection writes an empty string. Errors exit with status 2 and do not emit a partial selection.

Discovery omissions are reported in JSON `skipped`; context output reports them on stderr without changing the rendered guidance. Selection skip precedence is minimum score, skill cap, cumulative target, then token budget. Thus `max_skills` wins over `target_reached` if both stop selection; below-minimum scores retain their own reason.

## Privacy and transport

No scoring request is sent without `--allow-upload`. Review the dry run first: **skill names and descriptions can contain private information too**. Requests contain the task, optional recent context, skill names/descriptions, and the scoring rubric. They never include discovered filesystem paths or full skill bodies. If you put a path or secret inside task/context/metadata, that text will be uploaded.

Scoring uses the fixed HTTPS endpoint `https://api.typesafe.ai/v1/systemone` with model `jev-1.13.0`. There is no endpoint override. The HTTP client does not follow redirects or inherit proxy settings. Connect timeout is 10 seconds; read/write/pool timeouts are 30 seconds. HTTP 429 and 529 get at most two retries, after 1 and 2 seconds. Other failures stop selection. Provider error bodies and credentials are not printed.

The documented API limits are 64k tokens per request and 32k tokens for state plus the longest question. Batches use conservative UTF-8 JSON byte ceilings of 48,000 and 24,000 respectively, leaving headroom rather than pretending `tiktoken` measures Jev tokens. Oversized task/context or a single question causes a local error. Batching preserves independent questions and repeats the same task/context for each batch.

Responses must contain exactly the requested IDs, score answer types, finite scores in 0–9, confidence in 0–1, the requested model, and nonnegative integer token usage. Duplicate JSON keys are rejected. There is no heuristic fallback, cached-score fallback, or fabricated result on failure.

## Discovery and limitations

Discovery recursively reads `SKILL.md` files with real YAML frontmatter. `name` and `description` must be nonempty strings. Invalid metadata and duplicate names with different contents cause an error. Hidden and archive directories are excluded. Directory symlinks are not traversed; file symlinks escaping the selected root are skipped.

Use `--skip-invalid` to explicitly omit files with invalid frontmatter instead of aborting. Each omission reports its root-relative file path and a static reason (`missing_frontmatter`, `invalid_yaml`, `invalid_metadata`, `missing_name`, or `missing_description`), never YAML snippets or parser exception details. Strict behavior remains the default. This option does not suppress unreadable files, invalid UTF-8, missing directories, or conflicting duplicate names. It never modifies installed skills.

The command does not load referenced files or inspect skill bodies for scoring. Descriptions may be incomplete, misleading, or contain prompt injection; treating them as data reduces but does not eliminate that risk. Selection quality needs evaluation on representative tasks. The tool does not verify that a selected skill's advice is correct or safe. Inspect returned instructions before using them.

API references: [request and response schema](https://docs.typesafe.ai/api.md), [model limits](https://docs.typesafe.ai/models.md).
