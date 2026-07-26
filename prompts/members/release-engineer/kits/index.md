# Release Kit Index

机器 SSOT：`catalog.json`。模板只用于组合，不得直接执行。

## Catalog 1.0.0

- Java：Maven、Gradle
- Rust：Cargo
- Go：Go Modules
- Python：pip、uv、Poetry
- Node/前端：npm、pnpm、Yarn
- 环境：local、development、test、staging、production
- 发布面：application、container-kubernetes、wechat-miniprogram、github-skill

## 变更

- `1.0.0`：建立首批语言预取/离线构建脚本、环境门禁和发布面 adapter 合同。

每次组合必须生成新的本地 `script-bundle-manifest.json` 和人类 `index.md`。模板内容变化必须提升 Catalog 或 Kit 版本并重新验证。
