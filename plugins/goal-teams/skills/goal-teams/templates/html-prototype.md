---
type: Goal Teams HTML Prototype Template
title: HTML 原型模板
---

何时使用：页面规格卡确认后、实现前，用可点击原型对齐布局与状态。

## 规则

- 单文件，CSS/JS/mock 数据内联，离线可打开；CDN 依赖在元数据写明 URL 与版本。
- 组件库确认后再生成原型。
- 元素带 `data-testid`（= 规格卡元素 ID）和 `data-component`（组件名）。
- `?state=<状态>` 可直接打开任一状态，供截图和 E2E 使用。
- mock 数据用虚构内容；不调用真实接口，不含密钥与个人信息。

## 骨架

```html
<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><title><页面名> 原型</title>
<script type="application/json" id="prototype-meta">
{"page": "PAGE-001", "spec": "<规格卡路径>",
 "componentLibrary": {"name": "<名称>", "version": "<版本>", "source": "<来源>"},
 "states": ["normal", "loading", "empty", "error", "disabled", "permission", "overlay"]}
</script>
<script type="application/json" id="mock-data">{"items": [{"name": "<示例>"}]}</script>
</head><body>
<nav data-testid="state-switch"></nav>
<input data-testid="search-input" data-component="Input">
<table data-testid="result-table" data-component="Table" data-when="normal disabled overlay"></table>
<p data-testid="loading" data-component="Spin" data-when="loading">加载中…</p>
<p data-testid="empty" data-component="Empty" data-when="empty">暂无数据</p>
<p data-testid="error" data-component="Alert" data-when="error">加载失败</p>
<p data-testid="forbidden" data-component="Result" data-when="permission">无权限</p>
<div role="dialog" data-testid="dialog" data-component="Modal" data-when="overlay"><弹窗></div>
<script>
const $ = id => JSON.parse(document.getElementById(id).textContent);
const state = new URLSearchParams(location.search).get('state') || 'normal';
document.querySelector('nav').innerHTML = $('prototype-meta').states.map(s => `<a href="?state=${s}">${s}</a>`).join(' ');
for (const el of document.querySelectorAll('[data-when]')) el.hidden = !el.dataset.when.split(' ').includes(state);
document.querySelector('table').innerHTML = $('mock-data').items.map(i => `<tr><td>${i.name}</td></tr>`).join('');
document.querySelector('input').disabled = state === 'disabled';
</script>
</body></html>
```

检查：E2E 逐状态截图，断言无 console 错误、组件库字段非空、关键元素有 `data-testid`；用 `gt run <任务ID> --kind e2e -- <命令>` 记录。
