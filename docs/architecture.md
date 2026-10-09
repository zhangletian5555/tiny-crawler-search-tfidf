# 架构

本项目的目标：给定种子 URL，礼貌地抓取一批网页，用 TF-IDF 建索引，并提供检索界面。
本文档说明"有哪些模块、数据怎么流动、每一层的输出格式是什么"。设计决策的来龙去脉见
[decisions.md](decisions.md)。

## 1. 四层数据流

```
config.toml ──► config.py ──► Settings（frozen dataclass）
                                   │
       seeds.txt ──┐               │  路径 / 礼貌参数 / 检索参数
                   ▼               ▼
              ┌─────────────────────────┐
              │ crawler   网络 → 归档    │
              └────────────┬────────────┘
                           ▼
              data/crawl/<run_id>/pages.zip + manifest.jsonl
                           │
                           ▼
              ┌─────────────────────────┐
              │ indexing  归档 → 索引    │
              └────────────┬────────────┘
                           ▼
              data/index/<index_id>/{meta.json, docs.jsonl, terms.jsonl, stats.json}
                           │
                           ▼
              ┌─────────────────────────┐
              │ search    索引 → 结果    │
              └────────────┬────────────┘
                           ▼
              ┌─────────────────────────┐
              │ web       结果 → 页面    │
              └─────────────────────────┘
```

依赖方向是单向的：`web → search → indexing → crawler → config`，`tokenizer` 被
`indexing` 与 `search` 共用（因此不属于任何一侧）。**不存在反向依赖**，也没有循环。
各层只通过磁盘上的产物通信，可以在不同时间、不同进程里分别运行。

## 2. 目录与职责

| 路径 | 职责 | 不做什么 |
|---|---|---|
| `config.py` | 读 `config.toml`、合并命令行覆盖、校验、产出配置对象 | 不提供全局单例，不读环境变量 |
| `tokenizer/` | HTML 切片、jieba 分词、停用词与噪声过滤 | 不碰文件系统以外的状态，不认识"文档"概念 |
| `crawler/` | 抓取、礼貌控制、压缩归档 | 不做分词，不做打分 |
| `indexing/` | 读归档、统计词频与文档频率、写索引产物 | 不发网络请求，不决定"查什么" |
| `search/` | 加载索引、TF-IDF 打分、排序 | 不读原始 HTML，不写索引产物 |
| `web/` | HTTP 接口与页面 | 不直接读磁盘产物，只通过 `SearchEngine` |
| `data/` | 全部运行时数据（不进版本库） | — |
| `resources/` | 种子示例等随项目分发的静态输入 | — |
| `ref/` | 历史作业代码，只读参考 | **任何代码都不导入它** |

## 3. 数据契约

### 3.1 抓取产物 `data/crawl/<run_id>/`

`<run_id>` 形如 `20260115-103000`。一个 run 目录就是一次可独立重放的抓取。

**`pages.zip`**：每一页一个成员，成员名 `<doc_id>.html`。按哈希直接定位单页，
无需解压整包。

**`manifest.jsonl`**：每行一条记录，**是文档主键的唯一来源**。

```json
{"doc_id": "3f9a1c7e20b45d81", "url": "https://ai.ruc.edu.cn/", "fetched_at": "2026-01-15T10:30:02+08:00", "status": 200, "content_type": "text/html; charset=utf-8", "title": "中国人民大学高瓴人工智能学院", "embedded_date": "2026-01-15", "body_bytes": 48213, "archive_member": "3f9a1c7e20b45d81.html", "seed_url": "https://ai.ruc.edu.cn/", "depth": 0, "version": 1}
```

`doc_id = sha1(normalized_url)[:16]`（64 bit）。同一 URL 重复抓到时 `version` 递增，
后写的覆盖先写的。URL 必须先归一化再哈希，否则同一页面的不同写法会产生不同主键。

### 3.2 索引产物 `data/index/<index_id>/`

| 文件 | 内容 |
|---|---|
| `meta.json` | 格式版本、构建时间、源 crawl run、`title_weight`、N、词典大小 |
| `docs.jsonl` | 每行 `{doc_id, url, title, title_len, body_len}` |
| `terms.jsonl` | 每行 `{term, df, postings: [[doc_id, title_tf, body_tf], ...]}`，按 term 排序 |
| `stats.json` | `{N, avg_title_len, avg_body_len, idf: {term: value}}` |

索引产物**自足**：`search` 只需要这一个目录，不需要 `data/crawl/`。
这样"换检索参数重建索引"不需要重新抓取。

### 3.3 运行状态 `data/state/crawl_state.json`

断点续爬所需的最小状态：待抓队列、已见 URL 集合、计数。写入采用
"写临时文件 + 原子替换"，避免中断时留下半截文件。

## 4. 检索模型（TF-IDF，当前唯一模型）

```
w_tf(t, d) = title_tf(t, d) * title_weight + body_tf(t, d)     title_weight 来自配置
w(t, d)    = (1 + log w_tf(t, d)) * idf(t)                     idf(t) = log(N / df(t))
doc_norm   = sqrt(Σ_t w(t, d)^2)
score(q, d) = Σ_{t ∈ q} w(t, d) / doc_norm * w_tf(t, q)
```

只用这一套公式。**刻意不做**的事：覆盖率惩罚、子词扩展、日期加权、文档长度预计算缓存。
这些在参考代码里都存在，但都是为了拟合特定题集而加的，会削弱泛用性；等主线跑通、
有了评测脚本之后，任何一项都可以作为独立改动加回来并对比效果。BM25 暂不实现。

## 5. 礼貌抓取

| 机制 | 规则 |
|---|---|
| robots.txt | `respect_robots = true` 时先取该 host 的 robots.txt 并缓存；`Disallow` 的路径不抓 |
| Crawl-delay | robots.txt 声明了 `Crawl-delay` 时，取它与 `default_delay_seconds` 中的较大值 |
| 限速粒度 | **按 host** 计时（不是按种子，也不是全局），同一 host 两次请求间隔不小于上述延迟 |
| 上限 | `max_pages` 限制单次运行总量，`max_pages_per_host` 限制单站深度扩张 |
| 重试 | 失败重试 `max_retries` 次，第 n 次等待 `n * retry_backoff_seconds`，不立即重入队 |
| 只抓网页 | 只接受 `text/html` 与 `application/xhtml+xml`，其余记录后跳过 |

## 6. 配置加载机制

```
argv ──┐
       ├─► 定位 config.toml ─► tomllib 解析 ─► 应用 --set 覆盖 ─► 校验 ─► Settings
config.toml ┘
```

- **定位**：`--config` 显式指定；否则从当前目录向上最多 3 级查找 `config.toml`。
- **唯一读者**：只有 `config.py` 打开配置文件，其他模块通过函数参数拿到配置对象。
- **覆盖**：`--set section.key=value`，未知节或未知键立即报错。
- **校验**：缺失键、类型不符、取值越界都直接报错退出，不猜默认值。
- **排障**：`--print-config` 打印合并后的生效配置后退出，不执行实际工作。

## 7. 里程碑

| 阶段 | 内容 | 验收 | 状态 |
|---|---|---|---|
| P0 | `config.py`、`config.toml`、`tokenizer/`、种子示例与读取、`crawler/__main__.py` 的 `--print-config` | `python -m pytest` 通过 | 已完成 |
| P1 | `crawler/link_extract.py`、`crawler/fetcher.py`、`python -m crawler fetch` | 测试通过 + 真实抓取可用 | 已完成 |
| P2 | `crawler/robots.py`、`throttle.py`、`frontier.py`、`store.py`、`state.py` | 产出 `pages.zip` + `manifest.jsonl`，可续爬，日志显示按 host 限速 | 待做 |
| P3 | `indexing/`（reader → builder → writer） | 归档往返一致，索引四个文件齐全 | 待做 |
| P4 | `search/`（tfidf、engine） | 固定查询能出结果，`title_weight` 改动可见效果 | 待做 |
| P5 | `web/`（模板 + JSON 接口） | 浏览器可检索 | 待做 |
