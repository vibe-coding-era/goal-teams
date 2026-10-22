"""Shipping fee rules (all amounts are integer cents)."""

FREE_SHIPPING_THRESHOLD_CENTS = 9900  # 满 99 元包邮
STANDARD_FEE_CENTS = 800
REMOTE_SURCHARGE_CENTS = 1500
REMOTE_REGIONS = frozenset({"XZ", "XJ", "QH"})


def shipping_fee(subtotal_cents, region=""):
    """Return the shipping fee in cents for an order subtotal.

    Orders that reach the free-shipping threshold ship for free.
    Remote regions always pay the surcharge on top.
    """
    if subtotal_cents < 0:
        raise ValueError("subtotal_cents must not be negative")
    surcharge = REMOTE_SURCHARGE_CENTS if region.upper() in REMOTE_REGIONS else 0
    if subtotal_cents > FREE_SHIPPING_THRESHOLD_CENTS:
        return surcharge
    return STANDARD_FEE_CENTS + surcharge
