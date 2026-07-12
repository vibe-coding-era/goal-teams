# Security Specialist Scripts

允许的确定性入口：

- `scripts/checks/check-security-fixtures.py`：安全负向 fixture。
- `scripts/checks/validate.py`：结构和协议 marker。
- `scripts/review/validate-dual-review.py`：safety 双重复核结构。

脚本通过不代表安全语义已批准。不得生成或执行外部主动扫描命令，不得回显 secret，不得以写入漏洞利用证明风险。授权充分时也只返回 Lead dispatch request。
