# 归档材料

这里存放不再参与构建、但需要留存的材料。**任何代码都不应 import 这里的模块。**

## ref-course-assignment/

课程作业时期的爬虫与检索代码，是本项目的出发点与素材来源。它已不再运行，
其经验与方法（哪些做法被保留、哪些被丢弃及原因）已整理进
[docs/decisions.md](../docs/decisions.md)。

保留它的理由：出题与作业评审会追溯到原始实现；如果将来需要核对"某个做法当初为什么
那样写"，原件比二手记述可靠。

其中的已知情况（详见 decisions.md）：

| 文件 | 情况 |
|---|---|
| `crawler.py` | 爬虫主体。延迟按种子而非按 host，且被 `fixed_delay=0.01` 覆盖成不限速；`import csv` 缺失导致 `get_seeds()` 会直接报错 |
| `weighted_bm25_search.py` | 当年提交的检索内核。含大量为拟合题集而调的阈值（`sub_weight`、`expand_df_threshold`、覆盖率惩罚曲线等） |
| `weighted.py` | 余弦 TF-IDF 版本，与上面重复实现了同一套 Posting/InvertedIndex/Query |
| `index.py` | 布尔倒排检索。`_intersection()` 里混入了并集逻辑，`logic_query(..., 'and')` 结果是错的 |
| `main.py` | Flask 骨架，只有 2 个路由；它引用的模板文件已丢失 |
| `project.py` | 草稿代码，功能已被 `crawler/link_extract.py` 覆盖 |
| `word_filter_list.txt` | 停用词表素材。实为"中文虚词表 + 整张英文停用词表 + 国家代码 + PDF 噪声"的拼接物，已整理为 `tokenizer/stopwords_zh.txt` |
| `seeds.csv` | 当年的种子列表，已整理为 `resources/seeds.example.txt` |
