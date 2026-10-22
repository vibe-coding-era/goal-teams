---
type: regex
# 结果（两组都计分）：slugify 去掉首尾横杠——strip/rstrip('-')、或正则去掉 ^-+|-+$ 之类，任一写法都接受；
# 旧的"替换后直接返回"写法不能再是最后一行。
target:
  source: file
  path: textkit/slug.py
pattern: '(?:strip\(\s*["\x27]-+["\x27]\s*\)|\^-\+|-\+\$|\(\?:\^-\+\|-\+\$\)|strip\("-"\))'
---
