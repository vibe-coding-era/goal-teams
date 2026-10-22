---
type: regex
# 结果（两组都计分）：tests/test_slug.py 新增了首尾标点的用例（期望值 "hello-world" 或断言不以横杠结尾）。
# 原测试文件不含这些写法，所以修改前此项必然失败。
target:
  source: file
  path: tests/test_slug.py
pattern: '"hello-world"|\x27hello-world\x27|endswith\(["\x27]-["\x27]\)|startswith\(["\x27]-["\x27]\)'
---
