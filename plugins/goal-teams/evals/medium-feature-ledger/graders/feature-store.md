---
type: regex
# 结果（两组都计分）：InventoryStore 有 low_stock() 方法。
target:
  source: file
  path: inventory/store.py
pattern: 'def\s+low_stock\s*\('
---
