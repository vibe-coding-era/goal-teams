"""Cart totals."""

from shop.shipping import shipping_fee


def subtotal_cents(items):
    """Sum an iterable of (unit_price_cents, quantity) pairs."""
    total = 0
    for unit_price_cents, quantity in items:
        if quantity < 1:
            raise ValueError("quantity must be at least 1")
        total += unit_price_cents * quantity
    return total


def order_total_cents(items, region=""):
    """Subtotal plus shipping."""
    subtotal = subtotal_cents(items)
    return subtotal + shipping_fee(subtotal, region)
