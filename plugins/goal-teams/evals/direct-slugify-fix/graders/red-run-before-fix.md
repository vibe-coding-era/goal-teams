---
type: regex
# 过程（两组都计分）：修复之前真的跑出过失败的测试（Red），而不只是在回复里这么说。
# 在第一条修改 textkit/slug.py 的 Edit/Write 调用之前，必须已出现 unittest 的 "FAILED (failures=N)"
# 或 pytest 的 "N failed"（只有 errors= 的失败多半是导入/语法错误，不算 Red）。
target: trace
pattern: '^(?:(?![^\n]*"name":"(?:Edit|Write|MultiEdit)","input":\{[^\n]*"file_path":"[^"]*textkit/slug\.py")[^\n]*\n)*?[^\n]*?(?:FAILED \(failures=\d|[1-9]\d* failed\b)'
---
