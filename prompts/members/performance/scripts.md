# Performance Specialist Scripts

允许的确定性入口：

- `scripts/benchmark/benchmark-runner.py`：只在 packet 给定的本地授权范围运行或检查 benchmark。
- `scripts/checks/validate.py`：结构与协议检查。
- `scripts/review/validate-dual-review.py`：comparison/safety review 结构。

脚本输出必须绑定环境、规模、命令和 candidate digest。不得连接生产数据库、调用外部负载、修改 SQL/页面实现或用单次退出码宣称提升。
