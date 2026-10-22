# inventory

用 JSON 文件记库存的小工具（仅 Python 标准库）。

## 用法

```bash
python3 -m inventory.cli --db inventory.json add A-1 扳手 --quantity 3
python3 -m inventory.cli --db inventory.json adjust A-1 -1
python3 -m inventory.cli --db inventory.json list
```

`data/sample-inventory.json` 是线上导出的一份老数据样例。

## 测试

```bash
python3 -m unittest
```
