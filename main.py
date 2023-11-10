from urllib.parse import quote

import itchat
import xmltodict

from config import config
from utils import summarize_content, github_repo, sanitize_string, get_url_html, get_text_from_html, setup_logger

text_msgs = {}
link_msgs = {}

command_set = {'help', 'summary', 'backup', 's', 'b'}

logger = setup_logger('wechat')


@itchat.msg_register('Text')
def text_reply(msg):
    logger.info(f"收到 {msg['User']['NickName']} 文本消息: {msg.text}")
    msg_from = msg['FromUserName']
    parsed = parse_command(msg.text)
    if parsed is None:
        return
    if parsed == {'help'}:
        return u'summary/s: 总结文章\nbackup/b: 备份文章'

    recent_link_msg = link_msgs.get(msg_from)
    recent_text_msg = text_msgs.get(msg_from)

    if recent_link_msg is None:
        recent_text_msg = msg
    elif abs(recent_link_msg['CreateTime'] - msg['CreateTime']) < 30:
        logger.info(f"开始处理 {msg['User']['NickName']} text: {msg.text}, link: {recent_link_msg.text}")
        res = handle_link(msg, recent_link_msg)
        logger.info(f"{msg['User']['NickName']} 处理结果: {res}")
        recent_link_msg = None
    else:
        recent_text_msg = msg
        recent_link_msg = None

    link_msgs[msg_from] = recent_link_msg
    text_msgs[msg_from] = recent_text_msg


@itchat.msg_register('Sharing')
def mm_reply(msg):
    logger.info(f"收到 {msg['User']['NickName']} 分享消息: {msg.text}")
    msg_from = msg['FromUserName']
    parsed = parse_link(msg)
    logger.info(f"解析分享消息: {parsed}")
    if parsed is None:
        return

    recent_link_msg = link_msgs.get(msg_from)
    recent_text_msg = text_msgs.get(msg_from)

    if recent_text_msg is None:
        recent_link_msg = msg
    elif abs(recent_text_msg['CreateTime'] - msg['CreateTime']) < 30:
        logger.info(f"开始处理 {msg['User']['NickName']} text: {recent_text_msg.text}, link: {msg.text}")
        res = handle_link(recent_text_msg, msg)
        logger.info(f"{msg['User']['NickName']} 处理结果: {res}")
        recent_text_msg = None
    else:
        recent_text_msg = None
        recent_link_msg = msg

    link_msgs[msg_from] = recent_link_msg
    text_msgs[msg_from] = recent_text_msg


def parse_command(text):
    texts = text.split()
    if len(texts) == 0:
        return None
    elif set(texts).issubset(command_set):
        return set(texts)


def parse_link(link_msg):
    if link_msg['AppMsgType'] != 5:
        return None
    xml = link_msg['Content']
    info = xmltodict.parse(xml)['msg']['appmsg']
    return {
        'title': info['title'],
        'url': info['url'],
        'description': info['des'],
        'source': info['sourcedisplayname']
    }


def handle_link(text_msg, link_msg):
    commands = parse_command(text_msg.text)
    to_summarize = 's' in commands or 'summary' in commands
    to_backup = 'b' in commands or 'backup' in commands
    link_info = parse_link(link_msg)
    logger.info(f"开始处理 {text_msg['User']['NickName']} text: {text_msg.text}, link: {link_info['url']}")
    try:
        html = get_url_html(link_info['url'], config['selenium_server'])
    except Exception as e:
        logger.error(f"😿 文章->{link_info['url']} selenium 抓取失败! Error: {str(e)}")
        itchat.send_msg(f"{link_info['url']} selenium 抓取失败!\n\n{str(e)}",
                        text_msg['FromUserName'])
        return
    s_res = None
    b_res = None
    if to_summarize:
        s_res = summarize(link_info, html)
        itchat.send_msg(s_res, text_msg['FromUserName'])
    if to_backup:
        b_res = backup(link_info, html)
        itchat.send_msg(b_res, text_msg['FromUserName'])
    return [s_res, b_res]


def summarize(link_info, html):
    text = get_text_from_html(html)
    error_msg = 'no error'
    for i in range(3):
        try:
            response = summarize_content(prompt=f"{config['ai_prompt']}{text}", api_key=config['zhipuai_key'])
            if response['code'] == 200:
                logger.info(f"🐱 文章->{link_info['url']} 摘要第生成成功! Cost: {response['data']['usage']}")
                msg = f"{response['data']['choices'][0]['content']}\n\n{response['data']['usage']}"
                return msg
            else:
                logger.warning(f"😿 文章->{link_info['url']} 摘要第 {i + 1} 次返回错误! Error: {response['msg']}")
                error_msg = response['msg']
                continue
        except Exception as e:
            logger.error()(f"😿 文章->{link_info['url']} 摘要第 {i + 1} 次生成失败! Error: {str(e)}")
            error_msg = str(e)
            continue
    return f"摘要生成失败，请稍后再试。\n\n{error_msg}"


def backup(link_info, html):
    title = sanitize_string(link_info['title'])
    mp_name = sanitize_string(link_info['source'])
    path = f"{config['github_path_prefix']}/{mp_name}/{title}.html"
    encode_path = f"{config['github_path_prefix']}/{quote(mp_name)}/{quote(title)}.html"
    try:
        github_repo.create_or_update_file(path=path, content=html, message=f'Add {path}')
        return f"origin_url: {link_info['url']}\n\n\
commit_url: https://github.com/{config['github_username']}/{config['github_repo']}/blob/master/{encode_path}\n\n\
page_url: https://{config['github_username']}.github.io/{config['github_repo']}/{encode_path}"
    except Exception as e:
        return f"备份失败，请稍后再试。{str(e)}"


itchat.auto_login(hotReload=True, enableCmdQR=2)
itchat.run()
