# OKF Graph（可选扩展）

把一个目录里的 OKF/Markdown 文档在内存中投影成 RDF 1.1 图：稳定 IRI、按修订区分的 claim、可追溯的证据链接。质量问题只记录，不阻断。

## 状态

- 可选扩展，不属于 Goal Teams 默认安装，Skill 与安装器都不加载它。
- Observe-only：finding 一律 `current_action=record`，不影响退出码。
- 未实现 SPARQL、SHACL 引擎、RDFS/OWL 推理（状态 `not_implemented`）。没有 finding 不等于检查通过。
- 不用数据库、网络或缓存；只有 `build --out` 写文件。
- Python 3.9+，仅标准库；需要 Linux/macOS（安全读取依赖 `dir_fd` 与 `O_NOFOLLOW`）。

## 为什么固定 Unicode 17

IRI 路径段先做 NFC 归一化再 percent-encode。Python 自带的 `unicodedata` 随解释器变化（3.9 是 Unicode 13，3.13 是 15.1），同一文档可能得到不同 IRI。本扩展用 `tools/generate_unicode17_nfc.py` 从固定的 UCD 文件生成 NFC 表；`lifecycle` 只做 ASCII 小写，时间戳校验也不依赖 `fromisoformat`。因此 3.9 与 3.13 的输出逐字节一致，测试固定了样例摘要。含未分配码位的标识直接报错。

## 输入规则

- `DIR` 是可信根。成员来源按优先级：`--file`（可重复）、`--map FILE`、根下的 `knowledge-map.md`（只读 `Members` 表）、根下全部 `*.md`（跳过隐藏项，不跟随符号链接）。
- 路径逃逸、符号链接成员、网络地址直接报错（`E_KG262_*`，退出码 2），不记为 finding。
- 文档身份来自 frontmatter 的 `namespace`、`knowledge_id`、`revision`。claim 是 `### CLM-…` 标题；关系写在 `#### Relations` 表；证据写在 `#### Evidence` 链接。
- 错误码与 finding 前缀沿用 `E_KG262_*`、`OBS-KG262-*`。

## 用法

```bash
G=extras/okf-graph/okf_graph_cli.py
python3 $G build docs/kb                       # N-Triples 输出到 stdout
python3 $G build docs/kb --format json --out kb.json
python3 $G lookup docs/kb "product:REQ-001@1#CLM-REQ-001-01"
python3 $G quality docs/kb
```

- 通用选项：`--map FILE`、`--file FILE`、`--base-iri IRI`。默认 base 是 `https://kg.example.invalid/okf`，正式使用请换成自己的 HTTPS 命名空间。
- `lookup` 先按 IRI 精确匹配，再按引用（`ns:id@rev#CLM-…` 或 `ns:id`）解析，最后按标题、别名、正文子串搜索。`--json` 输出查询结果。
- 退出码：0 成功；1 `lookup` 无匹配；2 用法或输入错误。
- Python API：`okf_graph.load_graph(dir)` 返回 `DocumentGraph`，提供 `observe`、`resolve`、`search`、`lookup` 等查询与 `to_ntriples()`。

## 测试

```bash
cd extras/okf-graph
python3 -m unittest discover -s tests -t .
python3 tools/generate_unicode17_nfc.py --check   # 生成表无漂移
```

`tests/fixtures/unicode17/` 存放固定的 Unicode 17.0.0 UCD 文件（约 6.4 MB，许可见同目录 `LICENSE.txt`），供测试和重新生成数据表使用。
