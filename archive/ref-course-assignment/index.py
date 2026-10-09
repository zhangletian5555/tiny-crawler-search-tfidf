import jieba
import os
from bs4 import BeautifulSoup
from collections import defaultdict
import re
import json

def str_check(string):
    has_digit = bool(re.search(r'\d', string))
    has_letter = bool(re.search(r'[a-zA-Z]', string))
    has_symbol = bool(re.search(r'[^a-zA-Z0-9\s]', string))

    if (has_letter and has_symbol) or has_digit:
        return False
    return True

class InvertedIndex:
    def __init__(self, filter_file, html_folder):
        self.filter_file = filter_file
        self.html_folder = html_folder
        self.filter_set = self._create_filter_list()
        for other_word in [' ', '\n', '|', '，', '！', '{', '}', '：',
                            '\t', '!', '++', '---', '&&', '%', '&#', '+&&', '._']:
            self.filter_set.add(other_word)

    def create_html_list(self):
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

        return word_filter

    def _cut_words(self, soup):
        word_list = list()
        title = soup.find('title')
        
        if title and title.string:
            try:
                temp_list = jieba.lcut(title.string)
                word_list += filter(lambda x:x not in self.filter_set and str_check(x), temp_list)
            except Exception as e:
                print(f"[Fail] error{e}")

        body = soup.find('body')
        if body:
            try:
                for text in body.find_all(string=True):
                    if text.string is not None:
                        temp_list = jieba.lcut(text.string)
                        temp_list = filter(lambda x:x not in self.filter_set and str_check(x), temp_list)
                        word_list += temp_list
            except Exception as e:
                print(f"[Fail] error{e}")

        return word_list

    def build_inverted_index(self):
        collections = self.create_html_list()
        inverted_index = defaultdict(list)
        for docid, file in enumerate(collections):
            file_path = os.path.join(self.html_folder, file)
            with open(file_path, 'r', encoding='utf-8') as f:
                soup = BeautifulSoup(f, 'html.parser')
                word_list = self._cut_words(soup)

                for word in set(word_list):
                    postings = inverted_index[word]
                    if not postings or postings[-1] != docid:
                        postings.append(docid)

            print(f"\rLoading Progress:{docid+1}", end='')

        return inverted_index

class Query:
    def __init__(self, inverted_index, collections):
        self.inverted_index = inverted_index
        self.collections = collections

    def _mapping(self, file_list):
        with open('url_mapping.json', 'r', encoding='utf-8') as f:
            url_mapping = json.load(f)

        result = []
        for file_name in file_list:
            result.append(url_mapping.get(file_name))

        return result

    def _intersection(self, l1, l2):
        i = j = 0
        answer = []
        while i < len(l1) and j < len(l2):
            if l1[i] == l2[j]:
                answer.append(l1[i])
                i += 1
                j += 1
            elif l1[i] < l2[j]:
                i += 1
            else:
                answer.append(l2[j])
                j += 1
         
        return answer

    def _union(self, l1, l2):
        i = j = 0
        answer = []
        while i < len(l1) and j < len(l2):
            if l1[i] == l2[j]:
                answer.append(l1[i])
                i += 1
                j += 1
            elif l1[i] < l2[j]:
                answer.append(l1[i])
                i += 1
            else:
                answer.append(l2[j])
                j += 1
        if i < len(l1):
            answer.extend(l1[i:])
        if j < len(l2):
            answer.extend(l2[j:])

        return answer

    def _difference(self, l1, l2):
        i = j = 0
        answer = []
        while i < len(l1) and j < len(l2):
            if l1[i] == l2[j]:
                answer.append(l1[i])
                i += 1
                j += 1
            elif l1[i] < l2[j]:
                answer.append(l1[i])
                i += 1
            else:
                j += 1
        if i < len(l1):
            answer.extend(l1[i:])

        return answer

    def logic_query(self, query_term, query_type):
        '''
        query_type: 只能在'AND', 'OR', 'ANDNOT'间选择
        '''
        l1 = self.inverted_index[query_term[0]][1:]
        query_type = str(query_type)

        if query_type == 'AND' or query_type == 'and':
            for q in query_term[1:]:
                l2 = self.inverted_index[q][1:]
                l1 = self._intersection(l1, l2)

        elif query_type == 'OR'or query_type == 'or':
            for q in query_term[1:]:
                l2 = self.inverted_index[q][1:]
                l1 = self._union(l1, l2)

        elif query_type == 'ANDNOT' or query_type == 'andnot':
            for q in query_term[1:]:
                l2 = self.inverted_index[q][1:]
                l1 = self._difference(l1, l2)

        else:
            print("\n[Fail] unsupported query type")

        result = [self.collections[docid] for docid in l1]
        return self._mapping(result)

if __name__ == '__main__':
    inverted_index_generater = InvertedIndex('word_filter_list.txt', 'html_doc')
    inverted_index = inverted_index_generater.build_inverted_index()
    collections = inverted_index_generater.create_html_list()

    with open('inverted_index.json', 'wt', encoding='utf-8') as f:
        json.dump(inverted_index, f, ensure_ascii=False, indent=4)

    query = Query(inverted_index, collections)

    print(f'\n{query.logic_query(('环境', '人工智能', '科研'), 'and')}')