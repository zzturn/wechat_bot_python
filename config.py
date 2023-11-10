import os
from dotenv import load_dotenv

load_dotenv()


config = {
    'zhipuai_key': os.getenv('ZHIPUAI_KEY', ''),
    'ai_prompt': os.getenv('AI_PROMPT', '请帮我总结一下这篇文章\n'),
    'github_token': os.getenv('GITHUB_TOKEN', ''),
    'github_username': os.getenv('GITHUB_USERNAME', ''),
    'github_repo': os.getenv('GITHUB_REPO', ''),
    'github_api_base': os.getenv('GITHUB_API_BASE', 'https://api.github.com').rstrip('/'),
    # Github 备份文件前缀，默认为 docs/wechat 文章完整路径为 GITHUB_FILE_PREFIX/公众号名称/文章标题.html
    'github_path_prefix': os.getenv('GITHUB_PATH_PREFIX', 'docs/wechat').strip('/'),
    # selenium 服务地址，如果是本地启动该项目，可以不填（需本地有 Chrome）
    'selenium_server': os.getenv('SELENIUM_SERVER', '')
}


