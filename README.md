# tiny-crawler-search-tfidf

一个小型学习项目：从种子 URL 出发，**礼貌地**抓取一批网页，用 **TF-IDF** 建索引，并提供检索界面。

数据流一共四层，每层只通过磁盘上的产物与下一层通信：

```
种子 URL ──► crawler ──► 归档(zip+清单) ──► indexing ──► 索引产物 ──► search ──► web
```

详细设计见 [docs/architecture.md](docs/architecture.md)，设计取舍与"为什么不用某些做法"见
[docs/decisions.md](docs/decisions.md)。

## 环境准备

需要 Python 3.11 以上（用到标准库 `tomllib`）。

```powershell
python -m venv .venv
& ".\.venv\Scripts\Activate.ps1"
python -m pip install -r requirements.txt
python -m pip install -e .
```

最后一步（可编辑安装）让 `python -m crawler` 在任意工作目录下都能用——否则
只能在项目根目录执行。开发期还可以装上静态检查工具：

```powershell
python -m pip install ruff mypy
python -m ruff check config.py crawler tokenizer tests
```

## 配置

`config.toml` 是唯一配置源：路径、礼貌抓取参数、检索参数都在里面。只有 `config.py` 会读它，
其他模块通过函数参数接收配置对象。

**路径规则**：配置文件里的相对路径、以及命令行 `--seeds` 的相对路径，都以**配置文件所在
目录**为基准（不是当前工作目录），并在加载时解析为绝对路径。因此换目录执行同一份配置仍
指向同一份数据，断点续爬不受影响。

临时改一项配置不必编辑文件：

```powershell
python -m indexing --set index.title_weight=1.0
python -m crawler --set crawl.max_pages=50
```

查看合并后的生效配置（不执行实际工作）：

```powershell
python -m crawler --print-config
```

## 运行

完整链路四步（四层各自独立，产物逐级传递）：

```powershell
python -m crawler  --config config.toml run     # 1. 抓取 → data/crawl/<run_id>/
python -m indexing --config config.toml         # 2. 建索引 → data/index/<index_id>/
python -m search   --config config.toml 人工智能  # 3. 命令行检索
python -m web      --config config.toml         # 4. 浏览器访问 http://127.0.0.1:8000/
```

常用参数：

| 命令 | 说明 |
|---|---|
| `python -m crawler run --resume` | 从断点继续抓取 |
| `python -m crawler fetch <URL>` | 只探测一个页面，打印状态、编码、标题与可抓链接数 |
| `python -m indexing --run-dir <目录>` | 索引指定的一次抓取（默认取最新） |
| `python -m search -k 5 <关键词>` | 控制返回条数 |
| 以上任意命令加 `--print-config` | 只打印合并后的生效配置 |

### 多站点试跑

仓库自带一份六站点配置，用于在多个学院站点上做初步检索验证：

```powershell
python -m crawler  --config config.multisite.toml run
python -m indexing --config config.multisite.toml
python -m web      --config config.multisite.toml
```

`resources/seeds.multisite.txt` 里说明了各站点的实际情况（其中一个站点已下线，
另一个的 robots.txt 会随访问频率返回 403——抓取器按"不允许"处理）。

**抓取产物与索引产物不进版本库**（`data/` 已被忽略）：它们是可以再生的派生数据，
体积随语料增长；需要版本化的是"怎么产生它"，也就是上面的配置与种子文件。
`multisite-crawl.log` 保留了真实抓取过程的日志（限速、跳过、失败原因），体积不大，便于复盘。

配置里有两个预算，注意它们的关系：

```toml
max_pages = 1500            # 总预算
max_pages_per_host = 250    # 单站预算
```

**总预算应不小于站点数 × 单站预算**。否则先被处理的站点会把总预算吃光，排在后面的站点
只能抓到首页——这一点在 [docs/decisions.md](docs/decisions.md) 的 D20 里有实测记录。

### 试跑结果与已知边界

一次实际试跑（`max_pages = 1500`，五个学院站点 + 学校新闻网等被顺链发现）：

| 项目 | 数值 |
|---|---|
| 归档页面 | 1500（doc_id 全部唯一） |
| 页面来源 | 物院 250 · 高瓴 249 · 信院 240 · 新闻网 233 · 数院 171 · 化院 137 · 学校主页 69 |
| 索引词条 | 47487 |
| 归档 / 索引体积 | 约 10 MB / 约 15 MB |
| robots.txt 拒绝 | 23 条 |
| 抓取失败 | 60 条（404、非网页内容为主） |
| 主键重复跳过 | 93 条（同一内容的不同入口，见 D11） |
| 单站预算放弃 | 5 个 host 共 1600 条链接 |

已知边界（都是取舍，不是缺陷）：

- **站点数超过总预算时仍会有站点抓不到**：这次统计学院就只有首页（总预算被前几站按 250
  的上限吃满）。要覆盖更多站点，把 `max_pages` 提到"站点数 × 单站预算"以上。
- **顺链会走出种子站点**：抓到了 `news.ruc.edu.cn`、`www.ruc.edu.cn` 等，也包括一个校内
  私有地址（`10.21.6.202`）。如需限定范围，可在 `link_extract` 加域白名单。
- **无产出上限的 CMS 会浪费预算**：化院附属站有大量
  `citationstylelanguage/get/*` 形式的导引链接，被单站预算挡住了大部分，但同类站点需要
  更细的 URL 规则才能省下预算。

### 后续可做的清理

- `ref/` 已完成使命（其中的方法与坑都已整理进 [docs/decisions.md](docs/decisions.md)），
  确认无用后可移出仓库，仓库体积会降到 0.1 MB 量级。
- 若要限定抓取范围，优先加的是域白名单，而不是调大预算。

## 目录

| 路径 | 说明 |
|---|---|
| `config.py` / `config.toml` | 配置加载与配置源 |
| `tokenizer/` | HTML 切片、分词、停用词与噪声过滤 |
| `crawler/` | 抓取、礼貌控制、压缩归档 |
| `indexing/` | 读取归档、构建索引产物 |
| `search/` | 加载索引、TF-IDF 打分 |
| `web/` | HTTP 接口与页面 |
| `data/` | 运行时数据，不进版本库 |
| `resources/` | 种子示例等静态输入 |
| `docs/` | 架构与决策文档 |
| `ref/` | 历史作业代码，只读参考，不被任何代码导入 |

## 测试

```powershell
python -m pytest          # 205 项，全部不触网
python -m ruff check      # 生产代码零告警
```

Windows PowerShell 默认用 GBK 解码程序输出，中文提示会显示成乱码。设一次环境变量即可：

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

各阶段的验收标准见 [docs/architecture.md §7](docs/architecture.md#7-里程碑)。

## 许可证

见 [LICENSE](LICENSE)。
