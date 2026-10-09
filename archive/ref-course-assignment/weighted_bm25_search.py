import jieba
import numpy as np
from collections import Counter
from collections import defaultdict
import os
from bs4 import BeautifulSoup
import re
import json
import time
import pickle
import dill as pickle

# ============================================================
# 本文件相对课程原始版本的优化说明(2026-08-29)
# ------------------------------------------------------------
# 1) [优化] 重写 Query.bm25_search:
#       覆盖率改为按"语义组"计算,日期 token 合并为 1 组,
#       不再各自稀释覆盖率;
# 2) [优化] 新增子词扩展方法 _expand_subterms:
#       解决查询词与文档分词粒度不一致导致的漏配
#       (如查询"足球赛" 对应正文"足球友谊赛");
# 3) [优化] 新增方法 _date_weight(日期权重封装)与 4 个可调参数
#       (sub_weight / sub_coverage / expand_df_threshold / sub_df_threshold);
# 4) [优化] bm25_search 默认 k 由 3 改为 20(与 search_engine.py 一致)。
# 其余部分(InvertedIndex 建索引、日期提取、BM25 公式、标题加权等)保持原样。
# ============================================================

def str_check(string):
    if not string or re.match(r'^[^a-zA-Z0-9\u4e00-\u9fa5]+$', string):
        return False
    if re.fullmatch(r'\d+', string):
        return False
    return True

class Posting(object):
    special_doc_id = -1
    def __init__(self, docid, title_tf=0, body_tf=0):
        self.docid = docid
        self.title_tf = title_tf
        self.body_tf = body_tf
    def __repr__(self):
        return "<docid: %d, title_tf: %d, body_tf: %d>" % (
            self.docid,
            self.title_tf,
            self.body_tf
            )

class InvertedIndex:
    def __init__(self, filter_file, html_folder, info_file='inverted_index_info_bm25.pkl', repeat_build=False):
        self.filter_file = filter_file
        self.html_folder = html_folder
        self.pkl_path = info_file
  
        self.filter_set = self._create_filter_list()
        self.collections = self._create_html_list()

        self.body_doc_length = {}
        self.title_doc_length = {}
        self.avg_body_length = 0
        self.avg_title_length = 0

        self.inverted_index = None
        self.N = 0
        self.df = defaultdict(int)
        self.title_doc_tf = defaultdict(dict)
        self.body_doc_tf = defaultdict(dict)
        self.idf = {}
        self.doc_titles = {}

        if repeat_build or not os.path.exists(self.pkl_path):
            self._build_inverted_index()
            self.save_info()
        else:
            self.load_info()

        with open('url_mapping.json', 'rb') as f:
            self.url_mapping = json.load(f)

    def _extract_date(self, text):
        date_tokens = []
        if not text:
            return date_tokens

        year_pattern = r'(\d{4})[年]'
        years = re.findall(year_pattern, text)
        for y in years:
            date_tokens.append(f"DATE_{y}")

        year_month_pattern = r'(\d{4})[-.年/](\d{1,2})[月]'
        matches = re.findall(year_month_pattern, text)
        for y, m in matches:
            date_tokens.append(f"DATE_{y}{int(m):02d}")

        year_month_day_pattern = r'(\d{4})[-.年/](\d{1,2})[-.月/](\d{1,2})[日号]?'
        matches = re.findall(year_month_day_pattern, text)
        for y, m, d in matches:
            token = f"DATE_{y}{int(m):02d}{int(d):02d}"
            date_tokens.append(token)

        month_day_pattern = r'(\d{1,2})[-.月/](\d{1,2})[日号]?'
        matches = re.findall(month_day_pattern, text)
        for m, d in matches:
            token = f"MD_{int(m):02d}{int(d):02d}"
            date_tokens.append(token)

        return date_tokens

    def _create_html_list(self):
        files = os.listdir(self.html_folder)
        sorted_files = sorted(files, key=lambda x : int(x.split('html_doc')[1]))
        collections = [file for file in sorted_files]

        return collections

    def _create_filter_list(self):
        word_filter = set()
        with open(self.filter_file, 'r', encoding='utf-8') as file:
            for word in file:
                if word != '\n':
                    word_filter.add(word.strip())

        for other_word in [' ', '\n', '|', '，', '！', '{', '}', '：',
                            '\t', '!', '++', '---', '&&', '%', '&#',
                            '+&&', '._', '（', '）', '年', '月', '日']:
            word_filter.add(other_word)

        return word_filter

    def _cut_words(self, soup):
        title_word_list = list()
        body_word_list = list()

        title = soup.find('title')
        if title and title.string:
            try:
                title_data_tokens = self._extract_date(title.string)
                title_word_list.extend(title_data_tokens)

                temp_list = jieba.lcut(title.string)
                title_word_list += filter(lambda x:x not in self.filter_set and str_check(x), temp_list)
            except Exception as e:
                print(f"[Fail] error{e}")

        body = soup.find('body')
        if body:
            try:
                for text in body.find_all(string=True):
                    if text.strip():
                        body_data_tokens = self._extract_date(text)
                        body_word_list.extend(body_data_tokens)

                        temp_list = jieba.lcut(text)
                        temp_list = filter(lambda x:x not in self.filter_set and str_check(x), temp_list)
                        body_word_list += temp_list
            except Exception as e:
                print(f"[Fail] error{e}")

        return title_word_list, body_word_list

    def _build_inverted_index(self):
        self.inverted_index = defaultdict(list)
        self.collections = self._create_html_list()
        self.N = len(self.collections)

        for docid, file in enumerate(self.collections):
            file_path = os.path.join(self.html_folder, file)
            with open(file_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'lxml')
                title_word_list, body_word_list = self._cut_words(soup)

                title_tag = soup.find('title')
                if title_tag and title_tag.string:
                    self.doc_titles[docid] = title_tag.string.strip()
                else:
                    self.doc_titles[docid] = file

                title_word_counter = Counter(title_word_list)
                body_word_counter = Counter(body_word_list)

                self.title_doc_tf[docid] = dict(title_word_counter)
                self.body_doc_tf[docid] = dict(body_word_counter)

                all_words = set(title_word_counter) | set(body_word_counter)

                for word in all_words:
                    self.inverted_index[word].append(
                        Posting(
                            docid,
                            title_word_counter.get(word, 0),
                            body_word_counter.get(word, 0)
                        )
                    )
                    self.df[word] += 1

            print(f"\rLoading Progress:{docid+1}", end='')
        print()

        self.idf = {}
        for word, df in self.df.items():
            self.idf[word] = np.log(
                (
                (self.N - df + 0.5) / 
                (df + 0.5) 
                ) + 1 
            )

        total_title_length = 0
        total_body_length = 0

        for docid in range(self.N):
            title_tf_dict = self.title_doc_tf.get(docid, {})
            body_tf_dict = self.body_doc_tf.get(docid, {})

            title_length = sum(title_tf_dict.values())
            body_length = sum(body_tf_dict.values())

            self.title_doc_length[docid] = title_length
            self.body_doc_length[docid] = body_length

            total_title_length += title_length
            total_body_length += body_length

        self.avg_title_length = total_title_length / self.N if self.N > 0 else 0
        self.avg_body_length = total_body_length / self.N if self.N > 0 else 0

    def save_info(self):
        info = {
            'inverted_index' : dict(self.inverted_index),
            'doc_titles' : self.doc_titles,

            'body_doc_length': self.body_doc_length,
            'title_doc_length': self.title_doc_length,
            'avg_body_length': self.avg_body_length,
            'avg_title_length': self.avg_title_length,

            'collections' : self.collections,
            'title_doc_tf' : self.title_doc_tf,
            'body_doc_tf' : self.body_doc_tf,
            'df' : dict(self.df),
            'idf' : self.idf,
            'N' : self.N
            }

        with open(self.pkl_path, 'wb') as f:
            pickle.dump(info, f)

    def load_info(self):
        with open(self.pkl_path, 'rb') as f:
            info = pickle.load(f)

        self.inverted_index = info['inverted_index']
        self.doc_titles = info.get('doc_titles', {})

        self.body_doc_length = info['body_doc_length']
        self.title_doc_length = info['title_doc_length']
        self.avg_body_length = info['avg_body_length']
        self.avg_title_length = info['avg_title_length']

        self.collections = info['collections']
        self.title_doc_tf = info['title_doc_tf']
        self.body_doc_tf = info['body_doc_tf']
        self.df = defaultdict(int, info['df'])
        self.idf = info['idf']
        self.N = info['N'] 

class Query:
    def __init__(self, inverted_index_obj: InvertedIndex):
        self.inverted_index = inverted_index_obj.inverted_index
        self.collections = inverted_index_obj.collections
        self.idf = inverted_index_obj.idf

        self.body_doc_length = inverted_index_obj.body_doc_length
        self.title_doc_length = inverted_index_obj.title_doc_length
        self.avg_body_length = inverted_index_obj.avg_body_length
        self.avg_title_length = inverted_index_obj.avg_title_length

        self.k1 = 1.5
        self.b = 0.75
        self.coverage_alpha = 2.0
        self.title_weight = 3.0
        # ---------- [优化] 以下 4 个参数为本次新增 ----------
        self.sub_weight = 0.3            # 子词命中时的分数权重(原查询词为 1.0)
        self.sub_coverage = 1.0          # 仅靠子词命中时的覆盖率贡献(1.0 = 视同整组命中)
        self.expand_df_threshold = 50    # 文档频率低于该值的查询词才做子词扩展
        self.sub_df_threshold = 200      # 子词的文档频率必须低于该值才被采用
        # ----------------------------------------------------
        
        self.doc_titles = inverted_index_obj.doc_titles

        self.filter_set = inverted_index_obj.filter_set
        self.url_mapping = inverted_index_obj.url_mapping

    def _mapping(self, file_list):
        result = []
        for docid, score in file_list:
            file_name = 'html_doc' + str(docid + 1)
            title = self.doc_titles.get(docid, "无标题")
            url = self.url_mapping.get(file_name, "#")
            result.append((url, title, str(round(score, 5))))
    
        return result

    def _extract_date(self, text):
            date_tokens = []
            if not text:
                return date_tokens
    
            year_pattern = r'(\d{4})[年]'
            years = re.findall(year_pattern, text)
            for y in years:
                date_tokens.append(f"DATE_{y}")
    
            year_month_pattern = r'(\d{4})[-.年/](\d{1,2})[月]'
            matches = re.findall(year_month_pattern, text)
            for y, m in matches:
                date_tokens.append(f"DATE_{y}{int(m):02d}")
    
            year_month_day_pattern = r'(\d{4})[-.年/](\d{1,2})[-.月/](\d{1,2})[日号]?'
            matches = re.findall(year_month_day_pattern, text)
            for y, m, d in matches:
                token = f"DATE_{y}{int(m):02d}{int(d):02d}"
                date_tokens.append(token)

            month_day_pattern = r'(\d{1,2})[-.月/](\d{1,2})[日号]?'
            matches = re.findall(month_day_pattern, text)
            for m, d in matches:
                token = f"MD_{int(m):02d}{int(d):02d}"
                date_tokens.append(token)
    
            return date_tokens

    def _cut_query_words(self, query_text):
        word_list = []

        if query_text != None and query_text != '':
            data_tokens = self._extract_date(query_text)
            word_list.extend(data_tokens)

            temp_list = jieba.cut(query_text)
            word_list += filter(lambda x:x not in self.filter_set and str_check(x), temp_list)

        return word_list

    def _bm25_score(self, tf, doc_length, avg_doc_length, idf):
        if tf <= 0:
            return 0.0
        if avg_doc_length <= 0:
            return 0.0

        numerator = tf * (self.k1 + 1)

        denominator = tf + self.k1 * (1 - self.b + self.b * doc_length / avg_doc_length)

        return idf * numerator / denominator

    def _get_coverage_alpha(self, total_terms):
        if total_terms <= 1:
            return 0.0
        alpha = 4 - 0.25 * (total_terms - 2)
        return max(0.5, alpha)

    # ============================================================
    # [优化] 新增:日期 token 权重封装。
    # 数值与原 bm25_search 内联逻辑完全一致(完整日期/MD 为 2,
    # 年-月 0.9、仅年份 0.8),只是抽出为独立方法便于统一管理。
    # ============================================================
    def _date_weight(self, term):
        if term.startswith("DATE_"):
            if len(term) == 9:
                return 0.8
            elif len(term) == 11:
                return 0.9
            elif len(term) == 13:
                return 2
            else:
                return 1.0
        elif term.startswith("MD_"):
            return 2
        return 1.0

    # ============================================================
    # [优化] 新增:稀有词的子词扩展。
    # 目的:解决"查询词切分粒度"与"文档索引切分粒度"不一致的问题。
    # 例:查询"足球赛"(jieba 切成 1 个词),答案页正文却是
    #     "足球友谊赛"(索引切成 足球/友谊/赛),原逻辑永远匹配不上;
    #     现在扩展出子词 足球/球赛 去检索,并按 sub_weight 计分。
    # 防噪:只扩展 df < expand_df_threshold 的稀有词,且只采用
    #     df < sub_df_threshold 的多字子词,排除 三个/教育/之家 等
    #     高频通用碎片,避免无关文档获得全覆盖信用。
    # ============================================================
    def _expand_subterms(self, term):
        if term in self.inverted_index:
            base_df = len(self.inverted_index[term])
            if base_df >= self.expand_df_threshold:
                return []
        subs = []
        try:
            for s in jieba.cut_for_search(term):
                if s == term or len(s) < 2:
                    continue
                if s in self.filter_set or not str_check(s):
                    continue
                sub_df = len(self.inverted_index.get(s, []))
                if sub_df == 0 or sub_df >= self.sub_df_threshold:
                    continue
                subs.append(s)
        except Exception:
            pass
        return subs

    # ============================================================
    # [优化] 重写:bm25_search(原实现保留在课程原始版本中)。
    # 核心变化:
    #   a) 覆盖率按"语义组"计算:每个普通查询词 = 1 组;
    #      所有日期 token(DATE_*/MD_*)合并为 1 组,避免 4 个日期
    #      token 各自稀释覆盖率,误伤只含"10月14日"的答案页;
    #   b) 每个组内先查原词、再查扩展子词(_expand_subterms),
    #      子词按 sub_weight 计分;
    #   c) 覆盖率惩罚改为:主词命中记 1.0、仅子词命中记 sub_coverage;
    #   d) 默认 k 由 3 改为 20(与 search_engine.py 的调用一致)。
    # ============================================================
    def bm25_search(self, query_text, k=20):
        query_terms = self._cut_query_words(query_text)
        if not query_terms:
            return []

        # [优化] 将查询词拆分为"内容词"与"日期词"两类
        content_terms = []
        date_terms = []
        for t in query_terms:
            if t.startswith("DATE_") or t.startswith("MD_"):
                date_terms.append(t)
            else:
                content_terms.append(t)

        # [优化] 构造匹配组:内容词各自成组(附带子词);日期合并为 1 组
        groups = []  # (base_term, [lookup terms], is_date)
        for t in content_terms:
            groups.append((t, [t] + self._expand_subterms(t), False))
        if date_terms:
            groups.append(("__DATE__", list(set(date_terms)), True))

        total_groups = len(groups)
        if total_groups == 0:
            return []
        dynamic_alpha = self._get_coverage_alpha(total_groups)

        scores = defaultdict(float)
        # [优化] 主词命中集合 与 子词命中集合 分开记录(用于覆盖率计算)
        base_matched = [set() for _ in groups]
        sub_matched = [set() for _ in groups]

        for gi, (base, terms, is_date) in enumerate(groups):
            for term in set(terms):
                if term not in self.inverted_index:
                    continue
                is_sub = (term != base)
                term_weight = self.sub_weight if (is_sub and not is_date) else 1.0
                idf_t = self.idf.get(term, 0)

                for posting in self.inverted_index[term]:
                    docid = posting.docid
                    if is_sub:
                        sub_matched[gi].add(docid)
                    else:
                        base_matched[gi].add(docid)

                    title_tf = posting.title_tf
                    title_length = self.title_doc_length.get(docid, 0)
                    title_score = self._bm25_score(title_tf, title_length, self.avg_title_length, idf_t)

                    body_tf = posting.body_tf
                    body_length = self.body_doc_length.get(docid, 0)
                    body_score = self._bm25_score(body_tf, body_length, self.avg_body_length, idf_t)

                    score = body_score + self.title_weight * title_score
                    score *= term_weight

                    if is_date:
                        score *= self._date_weight(term)

                    scores[docid] += score

        # [优化] 覆盖率按组计算:主词命中 1.0 / 仅子词命中 sub_coverage
        for docid in list(scores.keys()):
            matched = 0.0
            for gi in range(total_groups):
                if docid in base_matched[gi]:
                    matched += 1.0
                elif docid in sub_matched[gi]:
                    matched += self.sub_coverage
            coverage = matched / total_groups
            penalty = coverage ** dynamic_alpha
            scores[docid] *= penalty

        ranked = list(scores.items())
        ranked.sort(key=lambda x: -x[1])
        top_docs = ranked[:k]

        return self._mapping(top_docs)

if __name__ == '__main__':
    # rebuild_confirm = input("Whether choose to rebuild? : Y/N\n")
    
    # if rebuild_confirm == 'Y' or rebuild_confirm == 'y':
    #     rebuild_bool = True
    # elif rebuild_confirm == 'N' or rebuild_confirm == 'n':
    #     rebuild_bool = False
    # else:
    #     print("Please input valid instruction\n")
    #     exit(0)

    # if rebuild_bool:
    #     index = InvertedIndex('word_filter_list.txt', 'html_doc', repeat_build=True, title_weight=4.0)
    # else:
    #     index = InvertedIndex('word_filter_list.txt', 'html_doc', repeat_build=False, title_weight=4.0)

    index = InvertedIndex('word_filter_list.txt', 'html_doc', repeat_build=False)

    # start = time.perf_counter()
    
    query = Query(index)
    # print("\nsearch results:")
    # for r in query.bm25_search(query_text, k=40):
    #     print(r)
    # print()

    while True:
        query_text = input("Please input the text you want to search:\n")
        try:
            query_text = str(query_text)
        except:
            print("Please input valid content")

        with open('output.txt', 'w', encoding='utf-8') as f:
            for r in query.bm25_search(query_text, k=40):
                f.write(f'{r}\n')

    # end = time.perf_counter()
    # print(f"running time:{end - start}")