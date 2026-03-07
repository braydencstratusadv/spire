import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import requests
from pydantic import Field
from unidiff import PatchSet

from dandy import BaseIntel, Bot, Prompt


BACKEND_SKILLS = {
    'best-practices', 'form_views', 'models', 'queryset',
    'seeding', 'service-layer', 'service_layer',
}

FRONTEND_SKILLS = {
    'badge_templates', 'best-practices', 'button-template',
    'container-template', 'detail_templates', 'form_templates',
    'list_templates', 'tab-template', 'table-template', 'template',
}

GITHUB_API = 'https://api.github.com'

GH_TOKEN = os.environ['GH_TOKEN']
MAX_DIFF_LENGTH = 60000
OPENCODE_DIR = Path('.opencode')
PR_NUMBER = os.environ['PR_NUMBER']
REPO_FULL_NAME = os.environ['REPO_FULL_NAME']


@dataclass
class DiffFile:
    added: set[int] = field(default_factory=set)
    lines: set[int] = field(default_factory=set)
    path: str = ''
    text: str = ''


class ReviewCommentIntel(BaseIntel):
    body: str
    line: int
    path: str


class CodeReviewIntel(BaseIntel):
    comments: list[ReviewCommentIntel] = Field(default_factory=list)


def _relative_path(path: str) -> str:
    workspace = os.environ.get('GITHUB_WORKSPACE', '')

    if workspace and path.startswith(workspace):
        return path[len(workspace):].lstrip('/')

    return path


def _run_review(
    config: 'ReviewConfig',
    files: dict[str, DiffFile],
    github: 'GitHubClient',
) -> None:
    filtered = filter_by_extension(files, config.extensions)

    if not filtered.strip():
        return

    standards = load_opencode_prompt(config.skills)

    print(
        f'{config.label} standards:'
        f' {standards.estimated_token_count} estimated tokens',
    )
    print(f'{config.label} diff: {len(filtered)} chars')

    try:
        intel = config.bot().process(
            diff=filtered,
            standards=standards,
        )
    except Exception:
        print(f'{config.label} review failed', file=sys.stderr)
        return
    else:
        print(f'{config.label} review: {len(intel.comments)} comment(s)')

        lines = {
            path: entry.lines
            for path, entry in files.items()
        }

        comments = comments_from_intel(intel, lines, config.prefix)

        if comments:
            github.post_review(comments, config.label)


class GitHubClient:
    _headers = {
        'Accept': 'application/vnd.github+json',
        'Authorization': f'Bearer {GH_TOKEN}',
        'X-GitHub-Api-Version': '2022-11-28',
    }

    def _pr_url(self) -> str:
        return (
            f'{GITHUB_API}/repos/{REPO_FULL_NAME}'
            f'/pulls/{PR_NUMBER}'
        )

    def delete_previous_reviews(self) -> None:
        response = requests.get(
            f'{self._pr_url()}/reviews',
            headers=self._headers,
            timeout=30,
        )
        response.raise_for_status()

        for review in response.json():
            if not review.get('body', '').startswith('AI Code Review'):
                continue

            if review.get('user', {}).get('login', '') != 'github-actions[bot]':
                continue

            state = review.get('state', '')

            if state not in ('APPROVED', 'CHANGES_REQUESTED'):
                print(
                    f'Skipping review {review["id"]}'
                    f' (state: {state}, cannot dismiss).',
                )
                continue

            resp = requests.put(
                f'{self._pr_url()}/reviews/{review["id"]}/dismissals',
                headers=self._headers,
                json={'message': 'Superseded by new review.'},
                timeout=30,
            )

            if resp.status_code == 200:
                print(f'Dismissed previous review {review["id"]}.')
            else:
                print(
                    f'Failed to dismiss review {review["id"]}:'
                    f' {resp.status_code}',
                )

    def post_review(
        self,
        comments: list[dict],
        label: str,
    ) -> None:
        if not comments:
            return

        response = requests.post(
            f'{self._pr_url()}/reviews',
            headers=self._headers,
            json={
                'body': f'AI Code Review — {label}',
                'comments': comments,
                'event': 'COMMENT',
            },
            timeout=30,
        )
        response.raise_for_status()

        print(
            f'Posted {label} review:'
            f' {len(comments)} inline comment(s).',
        )


class _CodeReviewBot(Bot):
    intel_class = CodeReviewIntel

    def process(
        self,
        diff: str,
        standards: Prompt,
    ) -> CodeReviewIntel:
        prompt = Prompt()

        if standards.snippets:
            prompt.prompt(standards)
            prompt.lb()

        prompt.heading('Pull Request Diff')
        prompt.text(diff, triple_backtick=True)

        return self.llm.prompt_to_intel(prompt=prompt)


class BackendReviewBot(_CodeReviewBot):
    guidelines = Prompt().list([
        'Apply the project standards and best practices when reviewing.',
        'Do NOT comment on linting, formatting, or import ordering.'
        ' Ruff handles that.',
        'Do NOT comment on things that are clearly intentional'
        ' design decisions.',
        'Focus on model structure, service layer patterns, queryset usage,'
        ' form views, and general Python best practices.',
        'If the code follows all standards,'
        ' return an empty comments list.',
        'Only reference lines that appear in the diff.',
    ])
    role = 'Senior Django Developer'
    task = (
        'Review the Python and Django code in the provided diff'
        ' against the project standards.'
    )


class FrontendReviewBot(_CodeReviewBot):
    guidelines = Prompt().list([
        'Apply the project template standards and best practices'
        ' when reviewing.',
        'Do NOT comment on linting or formatting.',
        'Do NOT comment on things that are clearly intentional'
        ' design decisions.',
        'Focus on template inheritance, component usage,'
        ' Bootstrap structure, and Django Spire patterns.',
        'If the templates follow all standards,'
        ' return an empty comments list.',
        'Only reference lines that appear in the diff.',
    ])
    role = 'Senior Django Template Developer'
    task = (
        'Review the HTML templates in the provided diff'
        ' against the project standards.'
    )


@dataclass
class ReviewConfig:
    bot: type[_CodeReviewBot]
    extensions: tuple[str, ...]
    label: str
    prefix: str
    skills: set[str]


REVIEW_CONFIGS = [
    ReviewConfig(
        bot=BackendReviewBot,
        extensions=('.py',),
        label='Stratus Backend Bot',
        prefix='Stratus Backend Bot',
        skills=BACKEND_SKILLS,
    ),
    ReviewConfig(
        bot=FrontendReviewBot,
        extensions=('.html',),
        label='Stratus Frontend Bot',
        prefix='Stratus Frontend Bot',
        skills=FRONTEND_SKILLS,
    ),
]


def comments_from_intel(
    intel: CodeReviewIntel,
    lines: dict[str, set[int]],
    prefix: str,
) -> list[dict]:
    return [
        {
            'body': f'**{prefix}**: {comment.body}',
            'line': comment.line,
            'path': comment.path,
            'side': 'RIGHT',
        }
        for comment in intel.comments
        if comment.line in lines.get(comment.path, set())
    ]


def filter_by_extension(
    files: dict[str, DiffFile],
    extensions: tuple[str, ...],
) -> str:
    sections = [
        entry.text
        for path, entry in sorted(files.items())
        if path.endswith(extensions)
    ]

    filtered = ''.join(sections)

    if len(filtered) > MAX_DIFF_LENGTH:
        return (
            filtered[:MAX_DIFF_LENGTH]
            + '\n\n... (diff truncated due to size)'
        )

    return filtered


def load_opencode_prompt(names: set[str]) -> Prompt:
    prompt = Prompt()

    if not OPENCODE_DIR.is_dir():
        return prompt

    files = sorted(OPENCODE_DIR.rglob('*.md'))

    if not files:
        return prompt

    prompt.heading('Project Standards and Best Practices')
    prompt.lb()

    loaded = 0

    for file in files:
        content = file.read_text(encoding='utf-8').strip()

        if not content or content == 'pass':
            continue

        if file.parent.name not in names and file.stem not in names:
            continue

        path = file.relative_to(OPENCODE_DIR)
        prompt.sub_heading(str(path))
        prompt.text(
            content,
            triple_backtick=True,
            triple_backtick_label='markdown',
        )
        prompt.lb()
        loaded += 1

    print(f'Loaded {loaded} relevant .opencode files')

    return prompt


def parse_diff(diff: str) -> dict[str, DiffFile]:
    files: dict[str, DiffFile] = {}
    patch = PatchSet(diff)

    for patched in patch:
        entry = DiffFile(
            path=patched.path,
            text=str(patched),
        )

        for hunk in patched:
            for line in hunk:
                if line.is_added:
                    entry.added.add(line.target_line_no)
                    entry.lines.add(line.target_line_no)
                elif line.is_context:
                    entry.lines.add(line.target_line_no)

        files[patched.path] = entry

    return files


def ruff_to_comments(results: list[dict]) -> list[dict]:
    return [
        {
            'body': (
                f'**Ruff [{v.get("code", "")}]'
                f'({v.get("url", "")})**: '
                f'{v.get("message", "")}'
            ),
            'line': v.get('location', {}).get('row', 0),
            'path': _relative_path(v.get('filename', '')),
            'side': 'RIGHT',
        }
        for v in results
    ]


def run_ruff(
    files: list[str],
    added: dict[str, set[int]],
) -> list[dict]:
    existing = [
        f for f in files
        if f.endswith('.py') and Path(f).is_file()
    ]

    if not existing:
        return []

    result = subprocess.run(
        [
            sys.executable, '-m', 'ruff', 'check',
            '--output-format=json', *existing,
        ],
        capture_output=True,
        text=True,
        check=False,
    )

    if result.stderr:
        print(f'Ruff stderr: {result.stderr}')

    if not result.stdout.strip():
        return []

    return [
        violation
        for violation in json.loads(result.stdout)
        if violation.get('location', {}).get('row', 0)
        in added.get(
            _relative_path(violation.get('filename', '')),
            set(),
        )
    ]


def main() -> None:
    with open('pr_diff.patch', 'r') as f:
        diff = f.read()

    if not diff.strip():
        print('AI review: empty diff, skipping.')
        return

    github = GitHubClient()
    github.delete_previous_reviews()

    files = parse_diff(diff)
    paths = list(files.keys())
    print(f'Changed files: {paths}')

    added = {
        path: entry.added
        for path, entry in files.items()
    }

    results = run_ruff(paths, added)
    print(f'Ruff results: {len(results)} violation(s)')

    comments = ruff_to_comments(results)

    if comments:
        github.post_review(comments, 'Ruff')

    matched = False

    for config in REVIEW_CONFIGS:
        if any(p.endswith(config.extensions) for p in paths):
            matched = True
            _run_review(config, files, github)

    if not matched:
        print(
            'No Python or HTML files in diff,'
            ' skipping AI review.',
        )


if __name__ == '__main__':
    main()
