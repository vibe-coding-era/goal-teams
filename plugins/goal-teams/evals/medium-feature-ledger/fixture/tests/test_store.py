import os
import tempfile
import unittest

from inventory.store import InventoryError, InventoryStore

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "inventory.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_list_is_sorted_by_sku(self):
        store = InventoryStore(self.path)
        store.add_item("B-2", "螺丝刀", 5)
        store.add_item("A-1", "扳手", 3)
        self.assertEqual([item.sku for item in store.list_items()], ["A-1", "B-2"])

    def test_save_and_reload(self):
        store = InventoryStore(self.path)
        store.add_item("A-1", "扳手", 3)
        store.save()
        self.assertEqual(InventoryStore(self.path).get("A-1").quantity, 3)

    def test_duplicate_sku_is_rejected(self):
        store = InventoryStore(self.path)
        store.add_item("A-1", "扳手")
        with self.assertRaises(InventoryError):
            store.add_item("A-1", "扳手")

    def test_adjust_cannot_go_negative(self):
        store = InventoryStore(self.path)
        store.add_item("A-1", "扳手", 1)
        with self.assertRaises(InventoryError):
            store.adjust("A-1", -2)

    def test_reads_sample_data_file(self):
        store = InventoryStore(os.path.join(PROJECT_ROOT, "data", "sample-inventory.json"))
        self.assertEqual([item.sku for item in store.list_items()], ["A-1", "B-2", "C-3"])


if __name__ == "__main__":
    unittest.main()
