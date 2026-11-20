"""CLI: python -m copilot "How do I reset my password?" --groups all-employees"""
import argparse
import json

from .answer import SupportCopilot, User


def main() -> None:
    parser = argparse.ArgumentParser(description="Ask the secure support copilot")
    parser.add_argument("question")
    parser.add_argument("--user", default="demo.user")
    parser.add_argument("--groups", default="all-employees", help="comma-separated access groups")
    args = parser.parse_args()
    user = User(args.user, {g.strip() for g in args.groups.split(",") if g.strip()})
    print(json.dumps(SupportCopilot.from_directory().answer(args.question, user).to_dict(), indent=2))


if __name__ == "__main__":
    main()
