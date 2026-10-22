---
type: tool_order
# 过程（两组都计分）：回归测试先于修复写入——第一次 Edit tests/test_shipping.py 早于第一次 Edit shop/shipping.py。
# tool_order 比较两侧各自"第一次"匹配的调用；input_match 匹配工具输入的 JSON 文本，这里按 file_path 区分文件。
# 先修源码、再补测试，或者根本没补测试，都不通过。
before:
  tool: Edit
  input_match: '"file_path"\s*:\s*"[^"]*tests/test_shipping\.py"'
after:
  tool: Edit
  input_match: '"file_path"\s*:\s*"[^"]*shop/shipping\.py"'
---
