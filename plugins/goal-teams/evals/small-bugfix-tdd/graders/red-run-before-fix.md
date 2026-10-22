---
type: regex
# 过程（两组都计分）：修复之前真的跑出过失败的测试（Red），而不只是在回复里这么说。
# trace 是整段 stream-json 轨迹，每行一条消息，工具结果也在其中。从开头逐行推进：
# 在第一条修改 shop/shipping.py 的 Edit/Write 调用之前，必须已出现 unittest 的 "FAILED (failures=N)"
# 或 pytest 的 "N failed"（只有 errors= 的失败多半是导入/语法错误，不算 Red）。
# 先修再测、修完才失败、或修复前只跑过全绿的套件，都不通过。
# 工具输出在轨迹里是 JSON 字符串，换行写作 \n 两个字符，所以 "N failed" 前不能用 \b。
target: trace
pattern: '^(?:(?![^\n]*"name":"(?:Edit|Write|MultiEdit)","input":\{[^\n]*"file_path":"[^"]*shop/shipping\.py")[^\n]*\n)*?[^\n]*?(?:FAILED \(failures=\d|[1-9]\d* failed\b)'
---
