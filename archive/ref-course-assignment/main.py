from flask import Flask, render_template, request

# 仅保留 BM25 模型内核
import weighted_bm25_search         # BM25 模型

app = Flask(__name__)

# ------------------------------------------------------------
# 配置区（如果文件路径不同，请在这里修改）
# ------------------------------------------------------------
WORD_FILTER_PATH = 'word_filter_list.txt'   # 词表/过滤词文件
HTML_DOC_PATH = 'html_doc'                  # 文档目录路径
REBUILD_INDEX = False                       # 是否重建索引（生产环境建议 False）

# ------------------------------------------------------------
# 初始化 BM25 索引（应用启动时加载，避免每次请求重复构建）
# ------------------------------------------------------------
print("🚀 正在加载 BM25 索引...")
bm25_index = weighted_bm25_search.InvertedIndex(WORD_FILTER_PATH, HTML_DOC_PATH, repeat_build=REBUILD_INDEX)

print("✅ 索引加载完成，服务已就绪。")


@app.route('/')
def index():
    """首页"""
    return render_template('index.html')


@app.route('/query', methods=['GET'])
def query():
    """处理搜索请求，统一使用 BM25 内核"""
    key = request.args.get('key', '').strip()

    # 如果关键词为空，直接返回空结果页
    if not key:
        return render_template('res.html', key=key, results=[])

    results = []

    # 使用 BM25 模型
    searcher = weighted_bm25_search.Query(bm25_index)
    raw_results = searcher.bm25_search(key, k=20)

    # ---------- 统一封装结果格式 ----------
    # BM25 的 raw_results 为 [(url, title, score), ...] 的列表
    for item in raw_results:
        # 兼容两种可能：元组 (url, title, ...) 或字典 {'url':..., 'title':...}
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            url, title = item[0], item[1]
        elif isinstance(item, dict):
            url = item.get('url')
            title = item.get('title')
        else:
            continue  # 格式异常则跳过

        results.append({'title': title, 'url': url})

    return render_template('res.html', key=key, results=results)


if __name__ == '__main__':
    # 监听所有网卡，端口 12345，开启调试模式
    app.run(host='0.0.0.0', port=12345, debug=True)
