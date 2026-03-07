import json
import os
import re
import subprocess
import sys
from pathlib import Path

import requests
from pydantic import Field

from dandy import BaseIntel, Bot, Prompt


GITHUB_API = 'https://api.github.com'

GH_TOKEN = os.environ['GH_TOKEN']
PR_NUMBER = os.environ['PR_NUMBER']
REPO_FULL_NAME = os.environ['REPO_FULL_NAME']

MAX_DIFF_LENGTH = 60000

OPENCODE_DIR = Path('.opencode')

BACKEND_SKILLS = {
    'best-practices', 'models', 'queryset', 'seeding',
    'service_layer', 'service-layer', 'form_views',
}

FRONTEND_SKILLS = {
    'best-practices', 'badge_templates', 'button-template',
    'container-template', 'detail_templates', 'form_templates',
    'list_templates', 'tab-template', 'table-template', 'template',
}


class ReviewCommentIntel(BaseIntel):
    path: str
    body: str
    line: int


class CodeReviewIntel(BaseIntel):
    comments: list[ReviewCommentIntel] = Field(default_factory=list)


def load_opencode_prompt(relevant_names: set[str]) -> Prompt:
    prompt = Prompt()

    if not OPENCODE_DIR.is_dir():
        return prompt

    md_files = sorted(OPENCODE_DIR.rglob('*.md'))

    if not md_files:
        return prompt

    prompt.heading('Project Standards and Best Practices')
    prompt.lb()

    loaded = 0

    for md_file in md_files:
        content = md_file.read_text(encoding='utf-8').strip()

        if not content or content == 'pass':
            continue

        parent_name = md_file.parent.name
        stem_name = md_file.stem

        if parent_name not in relevant_names and stem_name not in relevant_names:
            continue

        relative_path = md_file.relative_to(OPENCODE_DIR)
        prompt.sub_heading(str(relative_path))
        prompt.text(
            content,
            triple_backtick=True,
            triple_backtick_label='markdown',
        )
        prompt.lb()
        loaded += 1

    print(f'Loaded {loaded} relevant .opencode files')

    return prompt


class BackendReviewBot(Bot):
    role = 'Senior Django Developer'
    task = (
        'Review the Python and Django code in the provided diff'
        ' against the project standards.'
    )
    guidelines = Prompt().list([
        'Apply the project standards and best practices when reviewing.',
        'Focus on model structure, service layer patterns, queryset usage,'
        ' form views, and general Python best practices.',
        'Do NOT comment on linting, formatting, or import ordering.'
        ' Ruff handles that.',
        'Do NOT comment on things that are clearly intentional'
        ' design decisions.',
        'Only reference lines that appear in the diff.',
        'If the code follows all standards,'
        ' return an empty comments list.',
    ])
    intel_class = CodeReviewIntel

    def process(
        self,
        diff: str,
        standards_prompt: Prompt,
    ) -> CodeReviewIntel:
        prompt = Prompt()

        if standards_prompt.snippets:
            prompt.prompt(standards_prompt)
            prompt.lb()

        prompt.heading('Pull Request Diff')
        prompt.text(diff, triple_backtick=True)

        return self.llm.prompt_to_intel(prompt=prompt)


class FrontendReviewBot(Bot):
    role = 'Senior Django Template Developer'
    task = (
        'Review the HTML templates in the provided diff'
        ' against the project standards.'
    )
    guidelines = Prompt().list([
        'Apply the project template standards and best practices'
        ' when reviewing.',
        'Focus on template inheritance, component usage,'
        ' Bootstrap structure, and Django Spire patterns.',
        'Do NOT comment on linting or formatting.',
        'Do NOT comment on things that are clearly intentional'
        ' design decisions.',
        'Only reference lines that appear in the diff.',
        'If the templates follow all standards,'
        ' return an empty comments list.',
    ])
    intel_class = CodeReviewIntel

    def process(
        self,
        diff: str,
        standards_prompt: Prompt,
    ) -> CodeReviewIntel:
        prompt = Prompt()

        if standards_prompt.snippets:
            prompt.prompt(standards_prompt)
            prompt.lb()

        prompt.heading('Pull Request Diff')
        prompt.text(diff, triple_backtick=True)

        return self.llm.prompt_to_intel(prompt=prompt)


def get_diff() -> str:
    with open('pr_diff.patch', 'r') as f:
        return f.read()


def filter_diff_by_extensions(
    diff: str,
    extensions: tuple[str, ...],
) -> str:
    filtered_sections = []
    current_section = []
    current_file = None

    for line in diff.splitlines(keepends=True):
        file_match = re.match(r'^diff --git a/.+ b/(.+)$', line)

        if file_match:
            if current_file and current_file.endswith(extensions):
                filtered_sections.append(''.join(current_section))

            current_file = file_match.group(1)
            current_section = [line]
        else:
            current_section.append(line)

    if current_file and current_file.endswith(extensions):
        filtered_sections.append(''.join(current_section))

    filtered_diff = ''.join(filtered_sections)

    if len(filtered_diff) > MAX_DIFF_LENGTH:
        return (
            filtered_diff[:MAX_DIFF_LENGTH]
            + '\n\n... (diff truncated due to size)'
        )

    return filtered_diff


def parse_diff_lines(diff: str) -> dict[str, set[int]]:
    diff_lines = {}
    current_file = None
    current_line = 0

    for line in diff.splitlines():
        file_match = re.match(
            r'^diff --git a/.+ b/(.+)$', line,
        )
        if file_match:
            current_file = file_match.group(1)
            if current_file not in diff_lines:
                diff_lines[current_file] = set()
            continue

        hunk_match = re.match(
            r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', line,
        )
        if hunk_match:
            current_line = int(hunk_match.group(1))
            continue

        if current_file is None:
            continue

        if line.startswith('-') and not line.startswith('---'):
            pass
        else:
            diff_lines[current_file].add(current_line)
            current_line += 1

    return diff_lines


def parse_added_lines(diff: str) -> dict[str, set[int]]:
    added_lines = {}
    current_file = None
    current_line = 0

    for line in diff.splitlines():
        file_match = re.match(
            r'^diff --git a/.+ b/(.+)$', line,
        )
        if file_match:
            current_file = file_match.group(1)
            if current_file not in added_lines:
                added_lines[current_file] = set()
            continue

        hunk_match = re.match(
            r'^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@', line,
        )
        if hunk_match:
            current_line = int(hunk_match.group(1))
            continue

        if current_file is None:
            continue

        if line.startswith('+') and not line.startswith('+++'):
            added_lines[current_file].add(current_line)
            current_line += 1
        elif line.startswith('-') and not line.startswith('---'):
            pass
        else:
            current_line += 1

    return added_lines


def get_changed_files_from_diff(diff: str) -> list[str]:
    files = []

    for match in re.finditer(
        r'^diff --git a/.+ b/(.+)$', diff, re.MULTILINE,
    ):
        file_path = match.group(1)
        if file_path.endswith(('.py', '.html')):
            files.append(file_path)

    return files


def run_ruff(
    changed_files: list[str],
    added_lines: dict[str, set[int]],
) -> list[dict]:
    existing_files = [
        f for f in changed_files
        if Path(f).is_file() and f.endswith('.py')
    ]

    if not existing_files:
        return []

    try:
        result = subprocess.run(
            [
                sys.executable, '-m', 'ruff', 'check',
                '--output-format=json', *existing_files,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        print('ruff not found, skipping lint step.')
        return []

    if result.stderr:
        print(f'Ruff stderr: {result.stderr}')

    if not result.stdout.strip():
        return []

    results = json.loads(result.stdout)

    filtered = []

    for violation in results:
        raw_path = violation.get('filename', '')
        line = violation.get('location', {}).get('row', 0)
        relative_path = make_relative_path(raw_path)

        if line in added_lines.get(relative_path, set()):
            filtered.append(violation)

    return filtered


def ruff_results_to_comments(ruff_results: list[dict]) -> list[dict]:
    comments = []

    for violation in ruff_results:
        raw_path = violation.get('filename', '')
        line = violation.get('location', {}).get('row', 0)
        code = violation.get('code', '')
        message = violation.get('message', '')
        url = violation.get('url', '')

        relative_path = make_relative_path(raw_path)
        body = f'**Ruff [{code}]({url})**: {message}'

        comments.append({
            'path': relative_path,
            'body': body,
            'line': line,
            'side': 'RIGHT',
        })

    return comments


def make_relative_path(raw_path: str) -> str:
    workspace = os.environ.get('GITHUB_WORKSPACE', '')

    if workspace and raw_path.startswith(workspace):
        return raw_path[len(workspace):].lstrip('/')

    return raw_path


def delete_previous_reviews() -> None:
    response = requests.get(
        f'{GITHUB_API}/repos/{REPO_FULL_NAME}/pulls/{PR_NUMBER}/reviews',
        headers={
            'Authorization': f'Bearer {GH_TOKEN}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        },
        timeout=30,
    )
    response.raise_for_status()

    for review in response.json():
        body = review.get('body', '')
        user = review.get('user', {}).get('login', '')
        state = review.get('state', '')

        if not body.startswith('AI Code Review'):
            continue

        if user != 'github-actions[bot]':
            continue

        review_id = review['id']

        if state in ('APPROVED', 'CHANGES_REQUESTED'):
            resp = requests.put(
                f'{GITHUB_API}/repos/{REPO_FULL_NAME}'
                f'/pulls/{PR_NUMBER}/reviews/{review_id}'
                f'/dismissals',
                headers={
                    'Authorization': f'Bearer {GH_TOKEN}',
                    'Accept': 'application/vnd.github+json',
                    'X-GitHub-Api-Version': '2022-11-28',
                },
                json={'message': 'Superseded by new review.'},
                timeout=30,
            )

            if resp.status_code == 200:
                print(f'Dismissed previous review {review_id}.')
            else:
                print(
                    f'Failed to dismiss review {review_id}:'
                    f' {resp.status_code}',
                )
        else:
            print(
                f'Skipping review {review_id}'
                f' (state: {state}, cannot dismiss).',
            )


def post_review(
    inline_comments: list[dict],
    label: str,
) -> None:
    if not inline_comments:
        return

    payload = {
        'body': f'AI Code Review — {label}',
        'event': 'COMMENT',
        'comments': inline_comments,
    }

    response = requests.post(
        f'{GITHUB_API}/repos/{REPO_FULL_NAME}'
        f'/pulls/{PR_NUMBER}/reviews',
        headers={
            'Authorization': f'Bearer {GH_TOKEN}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
        },
        json=payload,
        timeout=30,
    )
    response.raise_for_status()

    print(
        f'Posted {label} review:'
        f' {len(inline_comments)} inline comment(s).',
    )


def comments_from_intel(
    review_intel: CodeReviewIntel,
    diff_lines: dict[str, set[int]],
    prefix: str,
) -> list[dict]:
    inline = []

    for comment in review_intel.comments:
        file_diff_lines = diff_lines.get(comment.path, set())

        if comment.line in file_diff_lines:
            inline.append({
                'path': comment.path,
                'body': f'**{prefix}**: {comment.body}',
                'line': comment.line,
                'side': 'RIGHT',
            })

    return inline


def main() -> None:
    diff = get_diff()

    if not diff.strip():
        print('AI review: empty diff, skipping.')
        return

    delete_previous_reviews()

    diff_lines = parse_diff_lines(diff)
    added_lines = parse_added_lines(diff)

    changed_files = get_changed_files_from_diff(diff)
    print(f'Changed files: {changed_files}')

    has_python = any(f.endswith('.py') for f in changed_files)
    has_templates = any(
        f.endswith('.html') for f in changed_files
    )

    ruff_results = run_ruff(changed_files, added_lines)
    print(f'Ruff results: {len(ruff_results)} violation(s)')
    ruff_comments = ruff_results_to_comments(ruff_results)

    if ruff_comments:
        post_review(ruff_comments, 'Ruff')

    if has_python:
        python_diff = filter_diff_by_extensions(diff, ('.py',))
        backend_standards = load_opencode_prompt(BACKEND_SKILLS)
        print(
            f'Backend standards:'
            f' {backend_standards.estimated_token_count}'
            f' estimated tokens',
        )
        print(f'Backend diff: {len(python_diff)} chars')

        try:
            backend_intel = BackendReviewBot().process(
                diff=python_diff,
                standards_prompt=backend_standards,
            )
            print(
                f'Backend review:'
                f' {len(backend_intel.comments)} comment(s)',
            )
            inline = comments_from_intel(
                backend_intel, diff_lines, 'Stratus Backend Bot',
            )
            if inline:
                post_review(inline, 'Stratus Backend Bot')
        except Exception as e:
            print(f'Backend review failed: {e}', file=sys.stderr)

    if has_templates:
        template_diff = filter_diff_by_extensions(
            diff, ('.html',),
        )
        frontend_standards = load_opencode_prompt(FRONTEND_SKILLS)
        print(
            f'Frontend standards:'
            f' {frontend_standards.estimated_token_count}'
            f' estimated tokens',
        )
        print(f'Frontend diff: {len(template_diff)} chars')

        try:
            frontend_intel = FrontendReviewBot().process(
                diff=template_diff,
                standards_prompt=frontend_standards,
            )
            print(
                f'Frontend review:'
                f' {len(frontend_intel.comments)} comment(s)',
            )
            inline = comments_from_intel(
                frontend_intel,
                diff_lines,
                'Stratus Frontend Bot',
            )
            if inline:
                post_review(inline, 'Stratus Frontend Bot')
        except Exception as e:
            print(
                f'Frontend review failed: {e}',
                file=sys.stderr,
            )

    if not has_python and not has_templates:
        print(
            'No Python or HTML files in diff,'
            ' skipping AI review.',
        )


if __name__ == '__main__':
    main()
