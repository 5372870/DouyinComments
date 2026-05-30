import asyncio
import logging
import os
from datetime import datetime
from typing import Any

import httpx
import pandas as pd
from tqdm import tqdm

from common import common

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('missing_fields.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

url = "https://www.douyin.com/aweme/v1/web/comment/list/"

with open('cookie.txt', 'r') as f:
    cookie = f.readline().strip()


async def get_comments_async(client: httpx.AsyncClient, aweme_id: str, cursor: str = "0", count: str = "50") -> dict:
    params = {"aweme_id": aweme_id, "cursor": cursor, "count": count, "item_type": 0}
    headers = {"cookie": cookie}
    params, headers = common(url, params, headers)
    response = await client.get(url, params=params, headers=headers)
    await asyncio.sleep(0.8)
    try:
        return response.json()
    except ValueError:
        return {}


async def fetch_all_comments_async(aweme_id: str) -> list[dict[str, Any]]:
    async with httpx.AsyncClient(timeout=600) as client:
        cursor = 0
        all_comments = []
        has_more = 1
        with tqdm(desc="Fetching comments", unit="comment") as pbar:
            while has_more:
                response = await get_comments_async(client, aweme_id, cursor=str(cursor))
                comments = response.get("comments", [])
                if isinstance(comments, list):
                    all_comments.extend(comments)
                    pbar.update(len(comments))
                has_more = response.get("has_more", 0)
                if has_more:
                    cursor = response.get("cursor", 0)
                await asyncio.sleep(1)
        return all_comments


def safe_get(data: dict, keys: list[str], default=None):
    result = data
    for key in keys:
        if isinstance(result, dict) and key in result:
            result = result[key]
        else:
            return default
    return result


def _extract_image_url(c: dict):
    image_list = c.get('image_list')
    if not image_list or not isinstance(image_list, list):
        return None
    try:
        return image_list[0]['origin_url']['url_list']
    except (IndexError, KeyError, TypeError):
        return None


def process_comments(comments: list[dict[str, Any]]) -> pd.DataFrame:
    data = []
    skipped = 0
    for c in comments:
        try:
            cid = c.get('cid')
            if not cid:
                logger.warning("评论缺少 cid 字段，已跳过: %s", {k: v for k, v in c.items() if k in ('cid', 'text')})
                skipped += 1
                continue
            row = {
                "评论ID": cid,
                "评论内容": c.get('text', ''),
                "评论图片": _extract_image_url(c),
                "点赞数": c.get('digg_count', 0),
                "评论时间": datetime.fromtimestamp(c['create_time']).strftime('%Y-%m-%d %H:%M:%S') if c.get('create_time') else '未知',
                "用户昵称": safe_get(c, ['user', 'nickname'], '未知'),
                "用户主页链接": f"https://www.douyin.com/user/{safe_get(c, ['user', 'sec_uid'], '')}" if safe_get(c, ['user', 'sec_uid']) else '',
                "用户抖音号": safe_get(c, ['user', 'unique_id'], '未知'),
                "用户签名": safe_get(c, ['user', 'signature'], '未知'),
                "回复总数": c.get('reply_comment_total', 0),
                "ip归属": c.get('ip_label', '未知')
            }
            missing = [k for k in ('cid', 'text', 'digg_count', 'create_time', 'user', 'reply_comment_total', 'ip_label') if k not in c]
            if missing:
                logger.warning("评论ID=%s 缺少字段: %s", cid, missing)
            data.append(row)
        except Exception as e:
            cid = c.get('cid', '未知')
            logger.warning("评论ID=%s 解析异常，已跳过: %s", cid, e)
            skipped += 1
    if skipped:
        print(f"⚠ 评论处理完成，跳过 {skipped} 条不完整数据（详见 missing_fields.log）")
    return pd.DataFrame(data)


def save(data: pd.DataFrame, filename: str):
    data.to_csv(filename, index=False)


async def main():
    aweme_id = input("Enter the aweme_id: ")
    all_comments = await fetch_all_comments_async(aweme_id)
    print(f"Found {len(all_comments)} comments.")
    comments_df = process_comments(all_comments)
    base_dir = f"data/{aweme_id}"
    os.makedirs(base_dir, exist_ok=True)
    comments_file = os.path.join(base_dir, "comments.csv")
    save(comments_df, comments_file)
    print("Comments saved to comments.csv")


if __name__ == "__main__":
    asyncio.run(main())
