"""textkit command line: ``python3 -m textkit.cli count <file>``."""

import argparse
import sys

from textkit.stats import word_count


def build_parser():
    parser = argparse.ArgumentParser(prog="textkit")
    sub = parser.add_subparsers(dest="command", required=True)
    count = sub.add_parser("count", help="count words in a file")
    count.add_argument("path")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "count":
        with open(args.path, encoding="utf-8") as handle:
            text = handle.read()
        print(word_count(text))
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
