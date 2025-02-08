from argparse import ArgumentParser
from datetime import datetime
import json
import random

from atproto import Client, client_utils, models
import requests


with open('proxy.json') as f:
    proxy_pool = json.loads(f.read())


def fetch_news():
    response = requests.get('https://news.163.com/special/cm_yaowen20200213/', allow_redirects=False)
    assert response.status_code == 200, response.status_code
    json_text = response.text[len('data_callback('):-1]
    news_data = json.loads(json_text)
    news_box = []

    for news in news_data:
        if news['point'] == '80':
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
    time_format = "%m/%d/%Y %H:%M:%S"
    news_time = datetime.strptime(news_time, time_format)
    pre_news_time = datetime.strptime(pre_news_time, time_format)
    return news_time > pre_news_time


def raw_fetch_img(url, proxy=None):
    response = requests.get(url, allow_redirects=False, timeout=60, proxies={'http': proxy, 'https': proxy} if proxy else None)
    assert response.status_code == 200
    assert response.headers['Content-Type'].startswith('image/')
    return respose


def fetch_img(url):
    try:
        response = raw_fetch_img(url)
    except Exception as error:
        print(f'fetch img: {url} error:{error}')
        proxy_data = random.choice(proxy_pool)
        try:
            response = raw_fetch_img(url, proxy_data['proxy'])
        except:
            return

    print(f'fetch img {url}')
    print(f'response headers: {response.headers}')
    print(f'response content length: {len(response.content)}')
    return response.content


def git_commit():
    import os
    os.system('git config --global user.email "xiaopengyou@live.com"')
    os.system('git config --global user.name "robot auto"')
    os.system('git add .')
    os.system('git commit -m "update pre news time"')


def git_push():
    import os
    os.system('git push')


def main(service, username, password, dev):
    news_box = fetch_news()
    print(f'fetch news: {len(news_box)}')
    with open('pre_news_time') as f:
        pre_news_time = f.read()
    
    post_box = []
    for news in news_box:
        if not is_later_news(news['time'], pre_news_time):
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
        
    post_box = post_box[:1]
    client = Client(base_url=service)
    client.login(username, password)

    for post in post_box:
        thumb = None
        if post['imgurl'] != '' and post['img'] is not None:
            thumb = client.upload_blob(post['img'])
            print(thumb.blob)
            assert thumb.blob.mime_type.startswith('image/'), post['imgurl']
        embed = models.AppBskyEmbedExternal.Main(
            external=models.AppBskyEmbedExternal.External(
                title=post['title'],
                description=post['title'],
                uri=post['url'],
                thumb=thumb.blob if thumb else None,
            )
        )
        client.send_post(post['post'], embed=embed)
        
    latest_news_time = post_box[0]['time']
    with open('pre_news_time', 'w') as f:
        f.write(latest_news_time)

    if not dev:
        git_commit()
        git_push()


def check_proxy():
    global proxy_pool

    filter_proxy_pool = []
    for proxy_data in proxy_pool:
        if proxy_data['protocol'] != 'http':
            continue

        try:
            response = raw_fetch_img('http://cms-bucket.ws.126.net/2025/0207/8a0b2e2ep00srbeyv004bc0009c0070c.png', proxy_data['proxy'])
            filter_proxy_pool.append(proxy_data)
        except:
            continue
    proxy_pool = filter_proxy_pool
    assert len(proxy_pool) > 0
    

if __name__ == '__main__':
    parser = ArgumentParser()
    parser.add_argument("--service", help="PDS endpoint")
    parser.add_argument("--username", help="account username")
    parser.add_argument("--password", help="account password")
    parser.add_argument("--dev", action="store_true")
    parser.add_argument("--check-proxy", action="store_true")
    args = parser.parse_args()
    if args.check_proxy:
        check_proxy()
    main(args.service, args.username, args.password, args.dev)
