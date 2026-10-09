from bs4 import BeautifulSoup
import requests
import time
import os
import queue
import socket
import json
from urllib.parse import urlparse, urljoin
from url_normalize import url_normalize
import pickle
import signal
import sys

def get_html(url, header=None, timeout=None):
    # 爬取网页的html格式文档
    header = header or {'User-Agent': 'Mozilla/5.0'}

    try:
        r = requests.get(url, headers=header, timeout=timeout)
        r.raise_for_status()

        # 检查打开的文件类型，阻止下载量大/不可扩展的链接的打开
        content_type = r.headers.get('Content-Type', '').lower()
        if not any(ct.lower() in content_type for ct in ['text/html', 'application/xhtml+xml']):
            print(f"[Skip] Non-HTML content: {content_type} for {url}")
            r.close()
            return None

        r.encoding = r.apparent_encoding
        html_doc = r.text
        r.close()
        return html_doc
    
    except requests.RequestException as e:
        print(f"[Fail] {url}\n       Error: {e}")
        return None

def get_urls(html_doc, url):
    # 爬取html文档中的链接
    all_links = set()
    if not html_doc:
        return all_links
    try:
        soup = BeautifulSoup(html_doc, 'html.parser')
    except Exception as e:
        print(f"[Fail] Parse error: {e}")
        return all_links

    VIDEO_EXTENSIONS = {'.mp4', '.avi', '.mov', '.wmv', '.flv', '.webm', '.mkv'}
    
    for anchor in soup.find_all('a'):
        href = anchor.attrs.get('href')
        if href != '' and href != None:
            href = href.strip()
            if href.startswith((
                '#',
                'javascript:',
                'mailto:',
                'tel:',
                'data:'
                )):
                continue
            href = urljoin(url, href)
            if urlparse(href).scheme not in ('http', 'https'):
                continue
            try:
                normalized = url_normalize(href)

                path = urlparse(normalized).path.lower()
                if any(path.endswith(ext) for ext in VIDEO_EXTENSIONS):
                    continue  

                all_links.add(normalized)
            except Exception as e:
                continue
    return all_links

def get_seeds(file):
    # 从可读取的csv文件中获得目标url；是否最终采用这种方式有待考虑
    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(script_dir, file)
    with open(file_path, 'r', encoding='utf-8') as csvfile:
        reader = csvfile.readlines()
        seeds_list = [row.strip() for row in reader]

    return seeds_list

class CrawlScheduler:
    # 管理种子并且创建初始可排序的队列；实现爬取主功能
    def __init__(self, fixed_delay=5, resume=False, retry=2):
        self.seeds = {}
        self.max_retry = retry
        self.retry_count = {}
        self.delay = fixed_delay
        self.resumed = resume
        self.prior = {
            'http://www.phys.ruc.edu.cn/', 'http://psy.ruc.edu.cn/','http://guoxue.ruc.edu.cn/',
            'https://envi.ruc.edu.cn/', 'http://ai.ruc.edu.cn/', 'https://gsai.ruc.edu.cn/'
        }
        self.mapping = {}

        self.current_url = None
        self.current_url_seed = None

        # 中断处理
        self.checkpoint_file = 'checkpoint.pkl'
        self.mapping_file = 'url_mapping.json'
        self.save_interval = 50
        self.last_save_count = 0
        if resume:
            self.load_checkpoint()
        else:
            self.seen = set()
            self.crawled_count = 0
            self.mapping = {}

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

    def load_checkpoint(self):
        if not os.path.exists(self.checkpoint_file):
            return
        with open(self.checkpoint_file, 'rb') as f:
            state = pickle.load(f)

        self.seen = set(state['seen'])
        self.crawled_count = state['crawled_count']
        self.last_save_count = state['last_save_count']

        for url, info in state['seeds'].items():
            self.seeds[url] = {
                'time' : info['time'],
                'priority' : info['priority'],
                'host' : info['host'],
                'url_queue' : queue.Queue()
            }

            for u in info['url_queue']:
                self.seeds[url]['url_queue'].put(u)

        if os.path.exists(self.mapping_file):
            with open(self.mapping_file, 'r', encoding='utf-8') as f:
                self.mapping = json.load(f)
        else:
            self.mapping = {}

    def save_checkpoint(self):
        # 这里有两个字典类数据结构需要转换后保存
        state = {
            'seen' : list(self.seen),
            'crawled_count' : self.crawled_count,
            'last_save_count' : self.last_save_count,
            'seeds' : {
                url : {
                    'time' : info['time'],
                    'priority' : info['priority'],
                    'host' : info['host'],
                    'url_queue' : list(info['url_queue'].queue)
                }
                for url, info in self.seeds.items()
            }
        }

        with open(self.checkpoint_file + '.tmp', 'wb') as f:
            pickle.dump(state, f)
        os.replace(self.checkpoint_file + '.tmp', self.checkpoint_file)

    def save_mapping(self):
        mapping = self.mapping

        with open(self.mapping_file + '.tmp', 'wt') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=4)
        os.replace(self.mapping_file + '.tmp', self.mapping_file)

    def _signal_handler(self, signum, frame):
        print("\n[Signal] Saving checkpoint...")

        if not self.current_url and not self.current_url_seed:
            seed_info = self.seeds.get(self.current_url_seed)
            if seed_info:
                seed_info['url_queue'].put(self.current_url)

        self.save_checkpoint()
        self.save_mapping()
        sys.exit(0)

    def add_seed(self, url):
        url = url_normalize(url)
        if url in self.seeds:
            return
        host = urlparse(url).hostname
        prior = 1 if url in self.prior else 0
        self.seeds[url] = {
            'time' : 0,
            'priority' : prior,
            'url_queue' : queue.Queue(),
            'host' : host
        }

    def add_seeds(self, urls):
        for url in urls:
            self.add_seed(url)

    def _distribute_links(self, links):
        # 通过主机名（host）判断种子之间关系/新得到链接是否属于主机/属于哪个主机
        host_map = {}
        for s_url, info in self.seeds.items():
            host_map.setdefault(info['host'], []).append(s_url)

        for link in links:
            if link in self.seen:
                continue
            host = urlparse(link).hostname
            if host and host in host_map:
                seed = host_map[host][0]
                self.seeds[seed]['url_queue'].put(link)
                self.seen.add(link)
        
    def _select_next(self):
        # 选择下一个进行爬取的url；核心逻辑是，判断时间上如何选入candidates并通过优先级排序，每次都选出第一个
        now = time.time()
        candidates = []
        for url, info in self.seeds.items():
            if info['url_queue'].empty():
                continue
            if info['time'] == 0 or now - info['time'] >= self.delay:
                candidates.append((url, info))
        if not candidates:
            return None, None
        candidates.sort(key=lambda x: (-x[1]['priority'], x[1]['time']))
        return candidates[0]

    def _wait_time(self):
        # 计算等待时间，核心逻辑是通过等待时间判断是否要使整个队列sleep；
        # 注意这里是考虑sleep的问题，而上一个函数是考虑时间上可否优化排序的问题
        now = time.time()
        min_wait = None
        for info in self.seeds.values():
            if info['url_queue'].empty():
                continue
            if info['time'] == 0:
                return 0
            wait = self.delay - (now - info['time'])
            if wait <= 0:
                return 0
            min_wait = wait if min_wait is None else min(min_wait, wait)
        return min_wait or 0

    def running(self, headers=None, timeout=10):
        # 核心运行步
        headers = headers or {'User-Agent': 'Mozilla/5.0'}

        if not self.resumed:
            for url in self.seeds:
                self.seeds[url]['url_queue'].put(url)
                self.seen.add(url)

        # print(f"Seeds: {len(self.seeds)}, Delay: {self.delay}s")

        while not all(info['url_queue'].empty() for info in self.seeds.values()):
            seed_url, info = self._select_next()
            if seed_url is None:
                time.sleep(min(self._wait_time(), 0.5))
                continue

            try:
                target = info['url_queue'].get_nowait()
            except queue.Empty:
                continue

            info['time'] = time.time()
            print(f"\n[Next] {target}\n       Seed: {seed_url}, Priority: {info['priority']}")

            html = get_html(target, headers, timeout)
            if html is None:
                print("[Skip] Download failed or non-HTML.")
                if self.retry_count.get(target, 0) < self.max_retry:
                    self.retry_count[target] = self.retry_count.get(target, 0) + 1
                    info['url_queue'].put(target)
                continue

            self.crawled_count += 1

            script_dir = os.path.dirname(os.path.abspath(__file__))
            folder_path = os.path.join(script_dir, 'html_doc')
            os.makedirs(folder_path, exist_ok=True)
            file_name = 'html_doc' + str(self.crawled_count)
            file_path = os.path.join(folder_path, file_name)
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(html)

            self.mapping[file_name] = target

            if self.crawled_count - self.last_save_count >= self.save_interval:
                self.save_checkpoint()
                self.last_save_count = self.crawled_count
                self.save_mapping()

            links = get_urls(html, target)
            print(f"       Found links: {len(links)}")
            if links:
                self._distribute_links(links)

            # status = ', '.join(f"{info['host']}={info['queue'].qsize()}" for info in self.seeds.values())
            # print(f"       Queues: {status}")

            print(f"\nTotal discovered URLs: {len(self.seen)}")
            print(f"Successfully crawled HTML pages: {self.crawled_count}")

        self.save_checkpoint()
        self.save_mapping()

if __name__ == '__main__':
    seeds = get_seeds('seeds.csv')

    resume_confirm = input("Whether choose to resume? : Y/N\n")

    if resume_confirm == 'Y' or resume_confirm == 'y':
        resume_bool = True
    elif resume_confirm == 'N' or resume_confirm == 'n':
        resume_bool = False
    else:
        print("Please input valid instruction\n")
        exit(0)

    if resume_bool:
        scheduler = CrawlScheduler(fixed_delay=0.01, resume=resume_bool)
    else:
        scheduler = CrawlScheduler(fixed_delay=0.01, resume=resume_bool)
        scheduler.add_seeds(seeds)

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'
    }
    scheduler.running(headers=headers, timeout=6)