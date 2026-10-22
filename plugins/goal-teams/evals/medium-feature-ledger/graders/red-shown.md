---
type: llm
# 结果（两组都计分）：汇报能证明新行为的回归测试先失败、后通过。测试文件里有没有新用例由 feature-tests / cli-tests 核对。
---

评审对象：助手完成"库存低于补货阈值"功能（reorder_level、InventoryStore.low_stock()、low-stock 子命令）后的最终交付汇报。

PASS（需同时满足）：
1. 汇报表明为新行为补了测试，并且这些测试在实现之前运行过、结果是失败（Red）。证据可以是失败的命令、用例名或失败原因（例如 AttributeError、AssertionError、unrecognized arguments），也可以是 TDD 记录工具给出的 Red→Green 配对计数（例如"TDD 红绿 2 对"）。
2. 汇报表明实现之后同一批测试运行通过（Green），给出命令、通过数量或回执之一。上面那种 Red→Green 配对计数同时算作第 1、2 条的证据。

FAIL：只说"已补测试、全部通过"而没有任何实现前失败的证据；明确说测试是在实现之后才写的；只有计划、没有运行结果；或配对计数为 0（例如"TDD 红绿 0 对"）且没有其他 Red 证据。
