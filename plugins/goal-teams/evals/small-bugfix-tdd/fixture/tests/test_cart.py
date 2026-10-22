import unittest

from shop.cart import order_total_cents, subtotal_cents


class CartTest(unittest.TestCase):
    def test_subtotal(self):
        self.assertEqual(subtotal_cents([(1999, 2), (500, 1)]), 4498)

    def test_small_order_adds_shipping(self):
        self.assertEqual(order_total_cents([(1999, 2)]), 3998 + 800)

    def test_big_order_ships_free(self):
        self.assertEqual(order_total_cents([(6000, 2)]), 12000)

    def test_quantity_must_be_positive(self):
        with self.assertRaises(ValueError):
            subtotal_cents([(100, 0)])


if __name__ == "__main__":
    unittest.main()
