import base64
import json
import re
import time
import logging
import sys

import requests
import zhipuai as zhipuai
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.service import Service

from config import config


def setup_logger(name, level=logging.DEBUG):
    """Function setup as many loggers as you want"""

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)-8s - %(message)s')

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    logger = logging.getLogger(name)
    logger.setLevel(level)
    logger.addHandler(handler)

    return logger


class GitHubRepo:
    def __init__(self, token, repo, base_url="https://api.github.com", branch="master"):
        self.token = token
        self.repo = repo
        self.headers = {
            "Authorization": f"token {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
        self.url = f'{base_url}/repos/{self.repo}'
        self.branch = branch

    def make_github_request(self, method, endpoint, data=None, params=None, is_json=True):
        url = f"{self.url}{endpoint}"
        headers = self.headers
        if is_json and data:
            data = json.dumps(data)
        response = requests.request(method, url, headers=headers, data=data, params=params)
        if response.ok:
            return response.json()
        else:
            response.raise_for_status()

    def get_branch_info(self):
        return self.make_github_request('GET', f'/branches/{self.branch}')

    def get_contents(self, path):
        try:
            file_info = self.make_github_request('GET', f'/contents/{path}?ref={self.branch}')
            content = base64.b64decode(file_info["content"]).decode("utf-8")
            return content
        except requests.HTTPError:
            return None

    def create_or_update_file(self, path, content, message):
        branch_info = self.get_branch_info()
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")
        data = {
            "message": message,
            "content": encoded_content,
            "branch": self.branch
        }
        try:
            file_info = self.make_github_request('GET', f'/contents/{path}?ref={self.branch}')
            if 'sha' in file_info:
                data['sha'] = file_info['sha']  # 文件存在，添加sha进行更新
        except requests.HTTPError as e:
            if e.response.status_code != 404:
                raise  # 如果不是404错误，重新抛出异常

        response = self.make_github_request('PUT', f'/contents/{path}', data)
        return response

    def delete_file(self, path, message):
        branch_info = self.get_branch_info()
        file_info = self.make_github_request('GET', f'/contents/{path}?ref={self.branch}')
        data = {
            "message": message,
            "sha": file_info["sha"],
            "branch": self.branch
        }
        if 'commit' in branch_info:
            data['branch'] = branch_info['commit']['sha']
        response = self.make_github_request('DELETE', f'/contents/{path}', data)
        return response

    def add_files_to_repo(self, files):
        """
        添加多个文件到GitHub仓库的一个commit中。
        :param files: 一个字典，包含文件路径和内容。
        """
        try:
            # 1. 获取最新的commit SHA
            commit_data = self.make_github_request('GET', f'/git/ref/heads/{self.branch}')
            commit_sha = commit_data['object']['sha']

            # 2. 获取最新commit的树的SHA
            commit = self.make_github_request('GET', f'/git/commits/{commit_sha}')
            tree_sha = commit['tree']['sha']

            # 3. 为新的文件创建blob
            blobs = []
            for file_path, content in files.items():
                blob_data = self.make_github_request('POST', '/git/blobs', {'content': content, 'encoding': 'utf-8'})
                blobs.append({'path': file_path, 'mode': '100644', 'type': 'blob', 'sha': blob_data['sha']})

            # 4. 创建一个新的树
            new_tree = self.make_github_request('POST', '/git/trees', {'base_tree': tree_sha, 'tree': blobs})

            # 5. 创建一个新的commit
            new_commit = self.make_github_request('POST', '/git/commits', {
                'parents': [commit_sha],
                'tree': new_tree['sha'],
                'message': 'Add multiple files'
            })

            # 6. 更新引用
            self.make_github_request('PATCH', f'/git/refs/heads/{self.branch}', {'sha': new_commit['sha']})
        except Exception as e:
            msg = f'An error occurred when add files to repo params: {files}, error: {e}'
            raise Exception(msg)


github_repo = GitHubRepo(token=config['github_token'],
                         repo=f"{config['github_username']}/{config['github_repo']}",
                         base_url=config['github_api_base'])


def sanitize_string(input_str):
    illegal_re = r'[~^:*?[\]\\/|<>".%]'
    control_re = r'[\x00-\x1f\x7f]'
    reserved_re = r'^(con|prn|aux|nul|com[0-9]|lpt[0-9])(\..*)?$'
    windows_re = r'^[. ]+'

    input_str = re.sub(illegal_re, '', input_str)
    input_str = re.sub(control_re, '', input_str)
    input_str = re.sub(reserved_re, '', input_str, flags=re.I)
    input_str = re.sub(windows_re, '', input_str)

    return input_str


def summarize_content(prompt: str, api_key: str, model_name="chatglm_turbo", **kwargs):
    zhipuai.api_key = api_key
    response = zhipuai.model_api.invoke(model=model_name,
                                        prompt=[{"role": "user", "content": prompt}],
                                        temperature=0.95,
                                        top_p=0.7,
                                        return_type="text",
                                        **kwargs)
    response.raise_for_status()
    # need test
    return {'content': response['data']['choices'][0]['content'], 'usage': response['data']['usage']}


def summarize_content_by_openai(prompt: str, api_key: str, base_url='https://api.openai.com/v1/chat/completions',
                                model_name="gpt-4", **kwargs):
    response = requests.post(base_url,
                             json={
                                 "messages": [{"role": "user", "content": prompt}],
                                 "model": model_name,
                             },
                             headers={
                                 'Authorization': f'Bearer {api_key}',
                                 'User-Agent': 'iOS App, Version 6.2.4',
                             },
                             timeout=120)
    response.raise_for_status()
    data = response.json()

    return {'content': data['choices'][0]['Message']['content'], 'usage': data['usage']}


def get_url_html(url: str, selenium_path: str = '', mobile: bool = False):
    """发起GET请求，获取文本

    Args:
        :param selenium_path: selenium 地址
        :param url: 目标网页
        :param mobile: 是否使用手机模式
    """
    # resp = send_get_request(url=url, params=params, timeout=timeout, **kwargs)
    html_content = None
    title = None
    driver = None
    mobile_emulation = {
        "deviceMetrics": {"width": 414, "height": 896, "pixelRatio": 1.0},
        "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 11_0 like Mac OS X) AppleWebKit/604.1.38 (KHTML, like Gecko) Version/11.0 Mobile/15A372 Safari/604.1"
    }
    try:
        options = webdriver.ChromeOptions()
        options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-gpu')
        options.add_argument('--disable-dev-shm-usage')
        if mobile:
            options.add_experimental_option('mobileEmulation', mobile_emulation)
        if selenium_path == '':
            driver = webdriver.Chrome(options=options)
        elif selenium_path.startswith('http'):
            driver = webdriver.Remote(
                command_executor=selenium_path,
                options=options)
        else:
            service = Service(selenium_path)
            driver = webdriver.Chrome(options=options)

        # 访问网页
        driver.get(url)

        # 获取网页的高度
        height = driver.execute_script("return document.body.scrollHeight")

        # 从顶部开始，模拟浏览网页的过程
        for i in range(0, height, 200):
            # 使用JavaScript代码控制滚动条滚动
            driver.execute_script(f"window.scrollTo(0, {i});")
            # 暂停一段时间，模拟人类浏览网页的速度
            time.sleep(0.2)

        driver.implicitly_wait(5)

        # 获取网页源代码
        source = driver.page_source
    except Exception as e:
        msg = f"selenium 发生异常 {str(e)}"
        raise Exception(msg) from e
    finally:
        if driver is not None:
            driver.quit()

    try:
        new_soup = BeautifulSoup(source, 'html.parser')

        # 下列处理其实都是针对微信公众号文章的，暂不清楚对其他网页是否有影响

        # 找到所有的<img>标签，将图片的src属性设置为data-src属性的值，并生成外链
        img_tags = new_soup.find_all('img')
        for img in img_tags:
            # 如果<img>标签有data-src属性
            if img.has_attr('data-src'):
                # 将src属性设置为data-src属性的值
                img['src'] = 'https://images.weserv.nl/?url=' + img['data-src']

        # 找到所有的<link>标签，如果href属性的值不是以https:开头，则添加https:前缀
        link_tags = new_soup.find_all('link')
        for link in link_tags:
            # 如果<link>标签有href属性
            if link.has_attr('href'):
                # 如果href属性的值不以https:开头
                if not link['href'].startswith('https:') and not link['href'].startswith('http:'):
                    # 在href属性的值前面添加https:
                    link['href'] = 'https:' + link['href']

        # 找到所有的<script>标签，删除这些标签
        script_tags = new_soup.find_all('script')
        for script in script_tags:
            # 删除<script>标签
            script.decompose()

        html_content = new_soup.prettify()
    except Exception as e:
        raise Exception(f"请求发生异常 {str(e)}") from e

    return html_content


def get_text_from_html(html) -> str:
    soup = BeautifulSoup(html, 'html.parser')
    return soup.get_text()


def test_add_files_to_repo():
    # 要添加的文件，以字典形式，键为文件路径，值为文件内容
    files_to_add = {
        'path/to/your/fisdffdsle1.txt': 'Contesdf nt of file1',
        'path/to/your/fil45e2.txt': 'Cont345ent of filefdgfdg2',
    }

    # 调用方法添加文件
    github_repo.add_files_to_repo(files_to_add)


def test_create_or_update_file():
    github_repo.create_or_update_file('te23sdfxt', 'te234st', 't6st')


def test_get_url_html():
    test_url = 'https://blog.csdn.net/qq_30934923/article/details/119803947'
    res = get_url_html(test_url)
    print(res)


def test_summarize_content_by_openai():
    prompt = "what is ojbk in Chinese"
    res = summarize_content_by_openai(prompt, api_key="sk-abc")
    print(res)


if __name__ == '__main__':
    test_summarize_content_by_openai()
    test_create_or_update_file()
    test_add_files_to_repo()
    test_get_url_html()
