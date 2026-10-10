# tiny-crawler-search-tfidf

一个小型学习项目：从种子 URL 出发，礼貌地抓取一批网页，用 TF-IDF 建索引，并提供检索界面。

数据流四层，每层只通过磁盘上的产物与下一层通信：

```
种子 URL ──► crawler ──► 归档(zip+清单) ──► indexing ──► 索引产物 ──► search ──► web
```

详细设计见 [docs/architecture.md](docs/architecture.md)，取舍理由与"为什么不用某些做法"见
[docs/decisions.md](docs/decisions.md)，实测数据见 [docs/runs.md](docs/runs.md)。

## 快速开始

需要 Python 3.11 以上（用到标准库 `tomllib`）。

```powershell
python -m venv .venv
& ".\.venv\Scripts\Activate.ps1"
python -m pip install -r requirements.txt
python -m pip install -e .        # 之后可在任意工作目录执行 python -m crawler
```

Windows PowerShell 默认按 GBK 解码程序输出，中文提示会显示成乱码。设一次环境变量即可：

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

四步跑通（四层各自独立，产物逐级传递）：

```powershell
python -m crawler  run              # 1. 抓取 → data/crawl/<run_id>/
python -m indexing                  # 2. 建索引 → data/index/<index_id>/
python -m search 人工智能            # 3. 命令行检索
python -m web                       # 4. 浏览器访问 http://127.0.0.1:8000/
```

前三步只读磁盘，不会联网重抓；索引产物是自足的，换检索参数重建索引不必重新抓取。

## 配置

`config.toml` 是唯一配置源，只有 [config.py](config.py) 读它，其他模块通过函数参数
接收配置对象。配置文件里的相对路径、以及命令行 `--seeds` 的相对路径，都以上一节所示
配置文件所在目录为基准，并在加载时解析为绝对路径——换目录执行同一份配置仍指向同一份
数据，断点续爬不受影响。

仓库自带三份配置，只有 `[crawl]` 一节不同（`[paths].seeds_file` 随之指向对应的种子）：

| 配置 | max_pages | 单站上限 | 延迟 | 抓取范围 | 用途 |
|---|---|---|---|---|---|
| [config.toml](config.toml) | 200 | 50 | 1.0s | 不限 | 第一次跑通，种子是示例站 |
| [config.multisite.toml](config.multisite.toml) | 1500 | 250 | 0.5s | 不限 | 五站点试跑 |
| [config.colleges.toml](config.colleges.toml) | 12000 | 2500 | 0.3s | 五个学院域 | 正式语料 |

所有入口都接受 `--config PATH`。临时改一项配置不必编辑文件：

```powershell
python -m crawler  --set crawl.max_pages=50
python -m indexing --set index.title_weight=1.0
python -m crawler  --print-config        # 只看合并后的生效配置，不执行实际工作
```

## 运行

```powershell
python -m crawler  --config config.toml run     # 抓取
python -m indexing --config config.toml         # 建索引
python -m search   --config config.toml 人工智能  # 检索
python -m web      --config config.toml         # 检索界面
```

| 命令 | 说明 |
|---|---|
| `python -m crawler run --resume` | 从断点继续抓取 |
| `python -m crawler fetch <URL>` | 只探测一个页面，打印状态、编码、标题与可抓链接数 |
| `python -m indexing --run-dir <目录>` | 索引指定的一次抓取（默认取最新） |
| `python -m search -k 5 <关键词>` | 控制返回条数；不带关键词则为交互模式 |
| 以上任意命令加 `--print-config` | 只打印合并后的生效配置 |

`Ctrl+C` 会在安全点收尾并保存断点，之后可用 `--resume` 继续。

## 用哪份配置抓

第一次跑用默认的 `config.toml`。要收学院语料就换配置，命令形状不变：

```powershell
python -m crawler  --config config.colleges.toml run
python -m indexing --config config.colleges.toml
python -m web      --config config.colleges.toml
```

`config.colleges.toml` 用 `crawl.allowed_hosts` 限定五个学院站点（含子域），范围外的
链接不入队，预算全部花在目标站点上；按域后缀匹配，登记 `phys.ruc.edu.cn` 会同时允许
`www.phys.ruc.edu.cn`。五个学院站点以 0.3s 间隔抓取约需 1 小时，**必须让它跑到正常
结束**——被强杀时 zip 的中央目录没写完，整个归档不可读，那一轮数据只能丢弃。

## 已知注意事项

- 单站预算是**上限**而不是配额。站点多的时候，`max_pages` 应不小于
  "站点数 × `max_pages_per_host`"，否则排在后面的站点只能抓到首页。
- 索引产物按时间戳命名，`search` 与 `web` 默认取最新一次构建。换配置抓取后要重新
  跑 `indexing`，否则检索到的仍是上一份语料。
- 若站点在 http 与 https 提供同一内容且不做重定向，会存成两篇文档。索引阶段默认按
  内容哈希去重（可关），检索结果因此不会重复。
- 限定抓取范围用 `crawl.allowed_hosts`，不是调大预算。

最近一次全面抓取的统计（8711 页 → 7438 篇文档、89742 词条，查询 2–10 ms）与边界
记录见 [docs/runs.md](docs/runs.md)。

## 测试与开发

```powershell
python -m pip install ruff mypy
python -m pytest          # 205 项，全部不触网
python -m ruff check      # 生产代码零告警
```

网络隔离靠依赖注入（测试传入假 session 与内存语料），因此抓取逻辑可以离线、确定性地
验证。ruff 与 mypy 的规则集见 [pyproject.toml](pyproject.toml)。

## 目录

| 路径 | 说明 |
|---|---|
| `config.py` / `config.toml` | 配置加载与配置源；另有两份抓取用配置 |
| `tokenizer/` | HTML 切片、分词、停用词与噪声过滤（被 indexing 与 search 共用） |
| `crawler/` | 抓取、礼貌控制、压缩归档 |
| `indexing/` | 读取归档、构建索引产物 |
| `search/` | 加载索引、TF-IDF 打分 |
| `web/` | HTTP 接口与页面 |
| `data/` | 运行时数据，不进版本库 |
| `resources/` | 种子文件 |
| `docs/` | 架构、决策与实测记录 |
| `archive/` | 归档材料（[课程作业时期的原始代码](archive/README.md)，任何代码都不导入它） |

## 许可证

见 [LICENSE](LICENSE)。
