"""Command line: python3 -m inventory.cli [--db FILE] <add|adjust|list> ..."""

import argparse
import sys

from inventory.store import InventoryError, InventoryStore


def build_parser():
    parser = argparse.ArgumentParser(prog="inventory")
    parser.add_argument("--db", default="inventory.json", help="data file (JSON)")
    sub = parser.add_subparsers(dest="command", required=True)

    add = sub.add_parser("add", help="add a new item")
    add.add_argument("sku")
    add.add_argument("name")
    add.add_argument("--quantity", type=int, default=0)

    adjust = sub.add_parser("adjust", help="change stock by DELTA")
    adjust.add_argument("sku")
    adjust.add_argument("delta", type=int)

    sub.add_parser("list", help="list all items")
    return parser


def main(argv=None, out=None, err=None):
    out = out or sys.stdout
    err = err or sys.stderr
    args = build_parser().parse_args(argv)
    store = InventoryStore(args.db)
    try:
        if args.command == "add":
            item = store.add_item(args.sku, args.name, args.quantity)
            store.save()
            print(f"added {item.sku}", file=out)
        elif args.command == "adjust":
            item = store.adjust(args.sku, args.delta)
            store.save()
            print(f"{item.sku}: {item.quantity}", file=out)
        elif args.command == "list":
            for item in store.list_items():
                print(f"{item.sku}\t{item.quantity}\t{item.name}", file=out)
    except InventoryError as exc:
        print(f"error: {exc}", file=err)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
