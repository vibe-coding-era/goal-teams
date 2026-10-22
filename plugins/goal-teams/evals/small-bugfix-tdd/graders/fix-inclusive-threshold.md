---
type: regex
# 结果（两组都计分）：包邮判断改成"达到阈值即包邮"（>= 或等价的 < 取反写法），严格大于的旧写法已去掉，
# 阈值常量仍是 9900（不接受把阈值改成 9899 之类的绕过）。
target:
  source: file
  path: shop/shipping.py
pattern: '^(?![\s\S]*subtotal_cents\s*>\s*FREE_SHIPPING_THRESHOLD_CENTS)(?=[\s\S]*FREE_SHIPPING_THRESHOLD_CENTS\s*=\s*9_?900\b)[\s\S]*(?:subtotal_cents\s*>=\s*FREE_SHIPPING_THRESHOLD_CENTS|FREE_SHIPPING_THRESHOLD_CENTS\s*<=\s*subtotal_cents|subtotal_cents\s*<\s*FREE_SHIPPING_THRESHOLD_CENTS|FREE_SHIPPING_THRESHOLD_CENTS\s*>\s*subtotal_cents)'
---
