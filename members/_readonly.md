## 补充规则（runner / read-only）

- 不修改源码、测试和文档。
- runner：运行检查命令，用 `gt run`、`gt tdd` 记录证据。
- read-only：只读文件，只跑不改变状态的命令（如 `gt status`、`gt diff`、`gt check`），不跑写入类 gt 命令。
- read-only 返回结论：pass|fail + 理由 + `file:line` 证据，由 Goal Lead 用 `gt review` 记录。
