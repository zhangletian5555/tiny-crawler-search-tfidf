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
    def __init__(self, filter_file, html_folder, info_file='inverted_index_info.pkl', repeat_build=False, title_weight=2):
        self.filter_file = filter_file
        self.html_folder = html_folder
        self.pkl_path = info_file

        self.title_weight = title_weight
  
        self.filter_set = self._create_filter_list()
        self.collections = self._create_html_list()

        self.inverted_index = None
        self.doc_length = {}
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
        for y, m, d in matches:
            token = f"DATE_{int(m):02d}{int(d):02d}"
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
                            '+&&', '._', '（', '）']:
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
                        body_data_tokens = self._extract_date(text.string)
                        body_word_list.extend(body_data_tokens)

                        temp_list = jieba.lcut(text.string)
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
            self.idf[word] = np.log10(self.N / df)

        for docid in range(self.N):
            length_sq = 0.0
            title_tf_dict = self.title_doc_tf.get(docid, {})
            body_tf_dict = self.body_doc_tf.get(docid, {})

            all_words = set(title_tf_dict) | set(body_tf_dict)

            for word in all_words:
                t_tf = title_tf_dict.get(word, 0)
                b_tf = body_tf_dict.get(word, 0)
                w_tf = t_tf * self.title_weight + b_tf

                w = w_tf * self.idf.get(word, 0)
                length_sq += np.square(w)
            self.doc_length[docid] = np.sqrt(length_sq) if length_sq > 0 else 1.0

    def save_info(self):
        info = {
            'inverted_index' : dict(self.inverted_index),
            'doc_titles' : self.doc_titles,
            'doc_length' : self.doc_length,
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
        self.doc_length = info['doc_length']
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
        self.doc_length = inverted_index_obj.doc_length
        self.doc_titles = inverted_index_obj.doc_titles
        self.title_weight = inverted_index_obj.title_weight

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
            for y, m, d in matches:
                token = f"DATE_{int(m):02d}{int(d):02d}"
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

    def cosine_search(self, query_text, k=3):
        query_terms = self._cut_query_words(query_text)
        if not query_terms:
            return[]
        tf_q = Counter(query_terms)
        scores = defaultdict(float)

        for term, tf in tf_q.items():
            if term not in self.inverted_index:
                continue
            idf_t = self.idf.get(term, 0)
            w_tq = tf * idf_t

            postings = self.inverted_index[term]
            for posting in postings:
                docid = posting.docid
                t_tf_d = posting.title_tf
                b_tf_d = posting.body_tf
                w_tf_d = self.title_weight * t_tf_d + b_tf_d

                w_td = w_tf_d * idf_t

                if term.startswith("DATE_"):
                    if len(term) == 9:
                        date_weight = 1
                    elif len(term) == 11:
                        date_weight = 0.9
                    elif len(term) == 13:
                        date_weight = 1.3
                    else:
                        date_weight = 1.0
                else:
                    date_weight = 1.0

                scores[docid] += w_tq * w_td * date_weight

        ranked = []
        for docid, score in scores.items():
            norm_score = score / self.doc_length[docid]
            ranked.append((docid, norm_score))
        ranked.sort(key=lambda x: -x[1])
        top_docs = ranked[0:k]

        return self._mapping(top_docs)

if __name__ == '__main__':
    rebuild_confirm = input("Whether choose to rebuild? : Y/N\n")
    
    if rebuild_confirm == 'Y' or rebuild_confirm == 'y':
        rebuild_bool = True
    elif rebuild_confirm == 'N' or rebuild_confirm == 'n':
        rebuild_bool = False
    else:
        print("Please input valid instruction\n")
        exit(0)

    if rebuild_bool:
        index = InvertedIndex('word_filter_list.txt', 'html_doc', repeat_build=True)
    else:
        index = InvertedIndex('word_filter_list.txt', 'html_doc', repeat_build=False)

    query_text = input("Please input the text you want to search:\n")
    try:
        query_text = str(query_text)
    except:
        print("Please input valid content")

    start = time.perf_counter()
    
    query = Query(index)
    print("\nsearch results:")
    for r in query.cosine_search(query_text, k=20):
        print(r)
    print()

    end = time.perf_counter()
    print(f"running time:{end - start}")