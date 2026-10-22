import unittest

from textkit.slug import slugify


class SlugifyTest(unittest.TestCase):
    def test_lowercases(self):
        self.assertEqual(slugify("Hello"), "hello")

    def test_spaces_become_one_dash(self):
        self.assertEqual(slugify("hello   big world"), "hello-big-world")

    def test_keeps_digits(self):
        self.assertEqual(slugify("v2 beta"), "v2-beta")


if __name__ == "__main__":
    unittest.main()
