from bs4 import BeautifulSoup
import jieba
import requests
import time
import urllib.request
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser
from url_normalize import url_normalize

def find_links(soup):
    all_links = set()
    for anchor in soup.find_all('a'):
        href = anchor.attrs.get('href')
        if href != None and href != '':
            all_links.add(href)

    return all_links

def cut_words(soup):
    filter_list = {'', ' ', '\n', '|', '\\', '=', '「', '」', '『', '』', ',', '.', ':', '。', '，', '>', '<', '\'', '\"', '(', ')'}
    word_list = list()
    title = soup.find('title')
    if title.string != None: 
        word_list += filter(lambda x:x not in filter_list, jieba.lcut(title.string))

    body = soup.find('body')
    for text in body.descendants:
        if text.string is not None:
            temp_list = jieba.lcut(text.string)
            temp_list = filter(lambda x:x not in filter_list, temp_list)
            word_list += temp_list

    return word_list

html_doc = open('example2.html', 'rt', encoding='utf-8')
soup = BeautifulSoup(html_doc, 'html5lib')
# url = "https://www.python.org"
# response = requests.get(url)
# soup = BeautifulSoup(response.text, 'html5lib')
print(soup.get_text())
# print(find_links(soup))
# print(cut_words(soup))