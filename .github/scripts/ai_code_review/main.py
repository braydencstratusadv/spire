import os

from ai_code_review.diff import DiffSet
from ai_code_review.github import GitHubClient
from ai_code_review.orchestrator import ReviewOrchestrator


def main() -> None:
    with open('pr_diff.patch', 'r') as file:
        diff = file.read()

    if not diff.strip():
        return

    github = GitHubClient(
        pr_number=os.environ['PR_NUMBER'],
        repo=os.environ['REPO_FULL_NAME'],
        token=os.environ['GH_TOKEN'],
    )

    github.delete_previous_comments()

    diff_set = DiffSet.from_patch(diff)

    orchestrator = ReviewOrchestrator(
        diff_set=diff_set,
        github=github,
    )

    orchestrator.run_ruff()
    orchestrator.run()


if __name__ == '__main__':
    main()
