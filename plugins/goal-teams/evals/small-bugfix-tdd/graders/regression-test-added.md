---
type: regex
# 结果（两组都计分）：tests/test_shipping.py 新增了恰好 99.00 元的边界用例（9900 分 / 99 * 100 / 阈值常量）。
# 原测试文件不含这些写法，所以修改前此项必然失败。
target:
  source: file
  path: tests/test_shipping.py
pattern: '\b9_?900\b|\b99_00\b|\b99\s*\*\s*100\b|FREE_SHIPPING_THRESHOLD_CENTS'
---
