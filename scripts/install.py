"""Install the skill locally without overwriting an existing destination."""
import argparse
from pathlib import Path
import shutil

SOURCE = Path(__file__).resolve().parents[1] / "skills/dify-kb-query"


def install(skills_dir):
    target = Path(skills_dir).expanduser().resolve() / "dify-kb-query"
    if target.exists() or target.is_symlink():
        raise ValueError(f"Destination already exists; nothing changed: {target}")
    if target == SOURCE or SOURCE in target.parents:
        raise ValueError("Destination cannot be inside the source skill")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(SOURCE, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--agent", choices=["codex", "claude-code"])
    choice.add_argument("--skills-dir", type=Path)
    parser.add_argument("--scope", choices=["user", "project"], default="user")
    parser.add_argument("--project-dir", type=Path, default=Path.cwd())
    args = parser.parse_args()
    directory = args.skills_dir
    if directory is None:
        base = Path.home() if args.scope == "user" else args.project_dir.resolve()
        directory = base / (".agents" if args.agent == "codex" else ".claude") / "skills"
    try:
        print(f"Installed: {install(directory)}")
        print("Configure the endpoint, allowed tags, and local API key before querying.")
    except (OSError, ValueError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
