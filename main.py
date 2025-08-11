from argparse import ArgumentParser
from datetime import datetime, timedelta
import json
import random
import os

from atproto import Client, client_utils, models
from atproto.exceptions import BadRequestError
import requests
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry


with open('proxy.json') as f:
    proxy_pool = json.loads(f.read())


with open('12h_news.json') as f:
    latest_12h_news = []
    latest_12h_news_url = []
    before_12h = datetime.now() - timedelta(hours=12)
    for item in json.loads(f.read()):
        if datetime.strptime(item['send_time'], "%m/%d/%Y %H:%M:%S") > before_12h:
            latest_12h_news.append(item)
            latest_12h_news_url.append(item['url'])


def fetch_news():
    s = requests.Session()
    retries = Retry(
        total=3,  # 总重试次数
        backoff_factor=1,  # 间隔时间因子，用于计算重试间隔时间
        status_forcelist=[101, 104],  # 遇到这些状态码时会触发重试
        allowed_methods=["GET"]  # 允许重试的方法
    )
    s.mount('https://', HTTPAdapter(max_retries=retries))
    response = s.get('https://news.163.com/special/cm_yaowen20200213/', allow_redirects=False)
    assert response.status_code == 200, response.status_code
    json_text = response.text[len('data_callback('):-1]
    news_data = json.loads(json_text)
    news_box = []

    for news in news_data:
        if news['point'] == '80':
            continue

        if not news["time"]:
            continue

        news_box.append({
            'title': news["title"],
            'source': news['source'],
            'time': news['time'],
            'tags': [item['keyname'] for item in news['keywords']],
            'url': news['docurl'],
            'imgurl': news['imgurl']
        })
    return news_box


def is_later_news(news_time, pre_news_time):
    if pre_news_time is None:
        return True
    time_format = "%m/%d/%Y %H:%M:%S"
    news_time = datetime.strptime(news_time, time_format)
    pre_news_time = datetime.strptime(pre_news_time, time_format)
    return news_time > pre_news_time


def raw_fetch_img(url, proxy=None):
    response = requests.get(url, allow_redirects=False, proxies={'http': proxy, 'https': proxy} if proxy else None)
    assert response.status_code == 200, f'status code: {response.status_code}'
    assert response.headers['Content-Type'].startswith('image/'), f'content type is not image'
    return response


def fetch_img(url):
    try:
        response = raw_fetch_img(url)
    except Exception as error:
        print(f'fetch img: {url} error:{error}')
        try:
            proxy_data = random.choice(proxy_pool)
            response = raw_fetch_img(url, proxy_data['proxy'])
        except:
            return
    return response.content


def git_commit():
    os.system('git config --global user.email "xiaopengyou@live.com"')
    os.system('git config --global user.name "robot auto"')
    os.system('git add .')
    os.system('git commit -m "update pre news time"')


def git_push():
    os.system('git push')


def send_post(client, post, embed, langs):
    try:
        client.send_post(post, embed=embed, langs=langs)
    except BadRequestError as error:
        if 'BlobTooLarge' in str(error) and embed.external.thumb is not None:
            embed.external.thumb = None
            send_post(client, post, embed, langs)
        else:
            raise error


def main(service, username, password, dev):
    client = Client(base_url=service if service != 'default' else None)
    client.login(username, password)

    try:
        if need_appeal():
            appeal_nsfw_label(client)
    except:
        pass

    news_box = fetch_news()
    print(f'fetch news: {len(news_box)}')
    with open('pre_news_time') as f:
        pre_news_time = f.read()
    
    post_box = []
    for news in news_box:
        if not is_later_news(news['time'], pre_news_time):
            continue

        if news['url'] in latest_12h_news_url:
            continue

        if news['imgurl'] != '':
            news['img'] = fetch_img(news['imgurl'])

        news['post'] = client_utils.TextBuilder().link(news['title'], news['url']).text(f'\n{news["time"]} ').tag(news['source'], news['source']).text('\n')
        
        for tag in news['tags']:
            news['post'].tag(f'#{tag}', tag).text(' ')

        post_box.append(news)

    print(f'need posts: {len(post_box)}')
    if not post_box:
        return
        
    latest_news_time = None
    post_status_error = False
    
    for post in post_box:
        thumb = None
        if post['imgurl'] != '' and post['img'] is not None:
            thumb = client.upload_blob(post['img'])

        embed = models.AppBskyEmbedExternal.Main(
            external=models.AppBskyEmbedExternal.External(
                title=post['title'],
                description=post['title'],
                uri=post['url'],
                thumb=thumb.blob if thumb else None,
            )
        )
        try:
            send_post(client, post['post'], embed=embed, langs=['zh'])

            if is_later_news(post['time'], latest_news_time):
                latest_news_time = post['time']

            latest_12h_news.append({
                'url': post['url'],
                'send_time': datetime.now().strftime('%m/%d/%Y %H:%M:%S')
            })
        except Exception as error:
            post_status_error = True
            print(f'error: {error} when handle post: {post["title"]} {post["url"]} {post["imgurl"]}')

    if latest_news_time is not None:
        with open('pre_news_time', 'w') as f:
            f.write(latest_news_time)
    
        with open('12h_news.json', 'w') as f:
            f.write(json.dumps(latest_12h_news))

        if not dev:
            git_commit()
            git_push()

    assert post_status_error is False


def check_proxy(auth_username, auth_password):
    global proxy_pool

    filter_proxy_pool = []
    for proxy_data in proxy_pool:
        protocol = f'http'
        proxy = f'{protocol}://{auth_username}:{auth_password}@{proxy_data["ip"]}:{proxy_data["port"]}'
        proxy_data['proxy'] = proxy
        try:
            response = raw_fetch_img('http://cms-bucket.ws.126.net/2025/0207/8a0b2e2ep00srbeyv004bc0009c0070c.png', proxy)
            filter_proxy_pool.append(proxy_data)
            print(f'proxy: {proxy_data["ip"]}:{proxy_data["port"]} good')
        except Exception as error:
            print(f'proxy: {proxy_data["ip"]}:{proxy_data["port"]} bad error: {error}')
            
    proxy_pool = filter_proxy_pool


def need_appeal():
    response = requests.get('https://public.api.bsky.app/xrpc/com.atproto.label.queryLabels?uriPatterns=did:plc:mmbknffnysobiitlszjovm3w&sources=did:web:cgv.hukoubook.com')
    return 'nsfw' in [x['val'] for x in response.json()['labels']]


def appeal_nsfw_label(client):
    dm_client = client.with_bsky_chat_proxy()
    dm = dm_client.chat.bsky.convo
    convo = dm.get_convo_for_members(
        models.ChatBskyConvoGetConvoForMembers.Params(members=['did:web:smite.hukoubook.com']),
    ).convo
    dm.send_message(
        models.ChatBskyConvoSendMessage.Data(
            convo_id=convo.id,
            message=models.ChatBskyConvoDefs.MessageInput(
                text=f"I'm labeled as NSFW, need action.",
            ),
        )
    )


if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument("--service", help="PDS endpoint")
    parser.add_argument("--username", help="account username")
    parser.add_argument("--password", help="account password")
    parser.add_argument("--webshare-username", help="webshare username")
    parser.add_argument("--webshare-password", help="webshare password")
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--check-proxy", action="store_true")
    args = parser.parse_args()
    if args.check_proxy:
        check_proxy(args.webshare_username, args.webshare_password)
    main(args.service, args.username, args.password, args.dev)
