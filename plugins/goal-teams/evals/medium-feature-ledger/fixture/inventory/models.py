"""Inventory data model."""

from dataclasses import asdict, dataclass


@dataclass
class Item:
    sku: str
    name: str
    quantity: int = 0

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        return cls(
            sku=str(data["sku"]),
            name=str(data["name"]),
            quantity=int(data.get("quantity", 0)),
        )
