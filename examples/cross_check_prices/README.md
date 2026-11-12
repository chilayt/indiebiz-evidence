# 30 秒看懂：多来源核实一条信息

你盯着两个商品、三个电商站点。第二天出了三件事：
- **site-b 的抓取器把小数点解析错了**：49 抓成了 490（10 倍）；
- **site-c 悄悄不再输出 stock 列**（页面改版，选择器失效）；
- **Nova Fan 只有 site-a 在报**（孤证）。

如果你只看某一个源，你会把 490 当成真涨价、把 stock 缺失当成"没库存"、把孤证当成已核实。
`cross_check` 把三个源摆一起，让这些**在你下结论之前**暴露出来。

## 跑起来（不用你自己的数据）

```bash
python examples/cross_check_prices/run_example.py
```

## 实际输出

```text
cross_check: Aurora Lamp   (sources: site-a, site-b, site-c)
  price    -> differs  (3 distinct sources)
      49       from site-a  @ 2099-01-02
      49       from site-c  @ 2099-01-02
      490      from site-b  @ 2099-01-02
  stock    -> agrees  (2 distinct sources)
      in_stock from site-a  @ 2099-01-02
      in_stock from site-b  @ 2099-01-02
      not reporting: site-c  (absent, NOT zero)

cross_check: Nova Fan   (sources: site-a)
  price    -> single_source  (1 distinct sources)
      29       from site-a  @ 2099-01-02
```

## 怎么读

- **Aurora 价格 differs**：49（site-a、site-c）对 490（site-b）。这个 10 倍跳变几乎肯定是
  抓取器小数点错误——**先去查 site-b，别信 490**。工具不替你宣判，但把矛盾和出处摆给你。
- **Aurora stock**：site-c 不再报告。**缺席，不是 0**，别当成"没库存"。
- **Nova Fan 是孤证**：只有 site-a 报。**没被交叉验证**，别当成已核实的事实。

## 换成你自己的数据

```bash
indiebiz-evidence import --source site-a --input ./from-site-a --db my.db
indiebiz-evidence import --source site-b --input ./from-site-b --db my.db
indiebiz-evidence crosscheck --db my.db --entity "你的实体名"
```

> 值相同 ≠ 事实已核实：仍需确认实体、口径/单位、时效，以及来源是否独立（两个站可能转载同一个错误）。