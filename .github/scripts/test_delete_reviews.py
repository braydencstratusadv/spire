import os
import sys

from pathlib import Path

import dotenv

project_root = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(project_root)

dotenv.load_dotenv('development.env')

from ai_code_review import GitHubClient  # noqa: E402


PR_NUMBER = '6'
REPO = 'braydencstratusadv/spire'


def main() -> None:
    token = os.environ.get('GH_TOKEN', '')

    if not token:
        print('GH_TOKEN not set.')
        return

    github = GitHubClient(
        pr_number=PR_NUMBER,
        repo=REPO,
        token=token,
    )

    print(f'Deleting previous comments on {REPO}#{PR_NUMBER}...')
    github.delete_previous_comments()
    print('Done.')


if __name__ == '__main__':
    main()
