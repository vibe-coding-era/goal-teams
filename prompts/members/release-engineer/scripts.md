# Release Engineer Scripts

仓库级 `scripts/` 只承载 Goal Teams 通用校验；本成员的确定性入口均位于隔离的 `runtime/`：

- `runtime/release_member.py check-evidence`：只读校验已有 Evidence，不运行测试。
- `runtime/release_member.py discover-scripts`：只读发现本地历史 bundle；输出准确版本、digest 和状态，供用户确认复用方式。
- `runtime/release_member.py plan`：选择内置 Kit 并生成 draft 发布计划。
- `runtime/release_member.py compose`：校验 plan approval，在用户本地 release root 生成不可变脚本 bundle。
- `runtime/release_member.py validate-bundle`：校验路径、digest、权限、危险操作和模板来源。
- `runtime/release_member.py execute`：校验精确绑定 execution_id/mode/operation 的 execution approval 后执行；默认 dry-run，并使用凭据清洗的闭集环境。
- `runtime/release_member.py status`：只读读取本地 release run 与 LOOP 状态。
- `runtime/validate_member.py`：独立检查本成员渐进加载、catalog、模板和 schema。

所有命令使用 Python 标准库。模板位于 `kits/`，只允许被组合器读取；不得直接执行。project adapter 必须是可审计 UTF-8 静态 Bash token 子集；任意二进制、项目 helper、通用 trampoline 或间接脚本拒绝，实际动作只能调用摘要、root ownership、capability 与 action_id 均绑定的 catalog host command `goal-teams-release-host-v245`。允许构建的 local/development 环境另需 catalog toolchain host `goal-teams-release-toolchain-host-v245`，按 language kit 绑定唯一 prefetch/build action，并冻结来源、版本、manifest digest 与 trusted-host provenance signature；两个 action 还必须产生 trusted-host 签名的 dependency/artifact digest receipt，runtime 强制 build offline、零全量测试且前后 dependency digest 相同。其他环境拒绝此权限。trusted-host signer、一次性 challenge 和隔离 runner 是外部能力依赖；缺失时保持 blocked，不能退化为自报批准。发现历史脚本不等于授权，未经用户确认不得自动复用。测试位于 `tests/`。
