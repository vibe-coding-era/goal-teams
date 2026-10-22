"""JSON-file backed inventory store."""

import json
import os

from inventory.models import Item


class InventoryError(Exception):
    """A user-facing inventory error (unknown SKU, bad quantity, ...)."""


class InventoryStore:
    def __init__(self, path):
        self.path = path
        self.items = {}
        if os.path.exists(path):
            self._load()

    def _load(self):
        with open(self.path, encoding="utf-8") as handle:
            data = json.load(handle)
        self.items = {row["sku"]: Item.from_dict(row) for row in data.get("items", [])}

    def save(self):
        payload = {"items": [item.to_dict() for item in self.list_items()]}
        tmp_path = self.path + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)

    def add_item(self, sku, name, quantity=0):
        if sku in self.items:
            raise InventoryError(f"SKU already exists: {sku}")
        if quantity < 0:
            raise InventoryError("quantity must not be negative")
        item = Item(sku=sku, name=name, quantity=quantity)
        self.items[sku] = item
        return item

    def get(self, sku):
        try:
            return self.items[sku]
        except KeyError:
            raise InventoryError(f"unknown SKU: {sku}") from None

    def adjust(self, sku, delta):
        item = self.get(sku)
        if item.quantity + delta < 0:
            raise InventoryError(f"insufficient stock for {sku}")
        item.quantity += delta
        return item

    def list_items(self):
        return [self.items[sku] for sku in sorted(self.items)]
