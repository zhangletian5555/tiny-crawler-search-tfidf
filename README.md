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

目前处于 P0 阶段（配置 + 分词），抓取与检索尚未实现。可先跑测试：

```powershell
python -m pytest
```

Windows PowerShell 默认用 GBK 解码程序输出，中文提示会显示成乱码。设一次环境变量即可：

```powershell
$env:PYTHONIOENCODING = "utf-8"
```

各阶段的验收标准见 [docs/architecture.md §7](docs/architecture.md#7-里程碑)。

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

## 许可证

见 [LICENSE](LICENSE)。
