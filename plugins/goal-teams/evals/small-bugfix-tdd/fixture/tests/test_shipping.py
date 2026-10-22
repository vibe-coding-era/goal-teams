import unittest

from shop.shipping import REMOTE_SURCHARGE_CENTS, STANDARD_FEE_CENTS, shipping_fee


class ShippingFeeTest(unittest.TestCase):
    def test_small_order_pays_standard_fee(self):
        self.assertEqual(shipping_fee(5000), STANDARD_FEE_CENTS)

    def test_large_order_ships_free(self):
        self.assertEqual(shipping_fee(15000), 0)

    def test_remote_region_always_pays_surcharge(self):
        self.assertEqual(shipping_fee(15000, "XZ"), REMOTE_SURCHARGE_CENTS)
        self.assertEqual(
            shipping_fee(5000, "xj"), STANDARD_FEE_CENTS + REMOTE_SURCHARGE_CENTS
        )

    def test_negative_subtotal_is_rejected(self):
        with self.assertRaises(ValueError):
            shipping_fee(-1)


if __name__ == "__main__":
    unittest.main()
