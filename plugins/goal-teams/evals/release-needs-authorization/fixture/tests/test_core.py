import unittest

from tinycalc import add, divide, multiply, subtract


class CoreTest(unittest.TestCase):
    def test_add_and_subtract(self):
        self.assertEqual(add(2, 3), 5)
        self.assertEqual(subtract(2, 3), -1)

    def test_multiply(self):
        self.assertEqual(multiply(4, 2.5), 10)

    def test_divide(self):
        self.assertEqual(divide(9, 3), 3)
        with self.assertRaises(ZeroDivisionError):
            divide(1, 0)


if __name__ == "__main__":
    unittest.main()
