import asyncio
import json
import logging
import httpx
import pandas as pd
from tqdm import tqdm
import os
from datetime import datetime
from typing import Optional
from common import common

reply_url = "https://www.douyin.com/aweme/v1/web/comment/list/reply/"

with open('cookie.txt', 'r') as f:
    cookie = f.readline().strip()

logging.basicConfig(
    level=logging.WARNING,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('skipped_replies.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


async def get_replies_async(client: httpx.AsyncClient, semaphore, comment_id: str, cursor: str = "0",
                            count: str = "50") -> dict:
    params = {"cursor": cursor, "count": count, "item_type": 0, "item_id": aweme_id, "comment_id": comment_id}
    headers = {"cookie": cookie}
    params, headers = common(reply_url, params, headers)
    async with semaphore:
        response = await client.get(reply_url, params=params, headers=headers)
        await asyncio.sleep(0.2)
        try:
            return response.json()
        except ValueError:
            return {}


async def fetch_replies_for_comment(client: httpx.AsyncClient, semaphore, comment_id: str, pbar: tqdm) -> list:
    cursor = 0
    all_replies = []
    has_more = 1
    while has_more:
        response = await get_replies_async(client, semaphore, comment_id, cursor=str(cursor))
        replies = response.get("comments", [])
        if isinstance(replies, list):
            all_replies.extend(replies)
        has_more = response.get("has_more", 0)
        if has_more:
            cursor = response.get("cursor", 0)
        await asyncio.sleep(0.2)
    pbar.update(1)
    return all_replies


def _safe_get_comment_image(comment: dict) -> Optional[str]:
    try:
        image_list = comment.get('image_list')
        if image_list and isinstance(image_list, list) and len(image_list) > 0:
            return image_list[0].get('origin_url', {}).get('url_list')
    except (KeyError, IndexError, TypeError, AttributeError):
        pass
    return None


def _safe_extract_reply(reply: dict, index: int) -> Optional[dict]:
    try:
        user = reply.get('user') or {}
        create_time = reply.get('create_time')
        sec_uid = user.get('sec_uid', '')
        reply_id = reply.get('reply_id', '')
        reply_to_reply_id = reply.get('reply_to_reply_id', '0')

        reply_to_username = ''
        try:
            if reply_to_reply_id == '0':
                reply_to_username = ''
            else:
                reply_to_username = reply.get('reply_to_username', '') or ''
        except (KeyError, IndexError, TypeError):
            pass

        return {
            "评论ID": reply.get('cid', ''),
            "评论内容": reply.get('text', ''),
            "评论图片": _safe_get_comment_image(reply),
            "点赞数": reply.get('digg_count', 0),
            "评论时间": datetime.fromtimestamp(create_time).strftime('%Y-%m-%d %H:%M:%S') if create_time else '',
            "用户昵称": user.get('nickname', '未知') or '未知',
            "用户主页链接": f"https://www.douyin.com/user/{sec_uid}" if sec_uid else '',
            "用户抖音号": user.get('unique_id') or user.get('short_id') or '未知',
            "用户签名": user.get('signature', '未知') or '未知',
            "回复的评论ID": reply_id,
            "具体的回复对象": reply_to_reply_id if reply_to_reply_id != '0' else reply_id,
            "回复给谁": reply_to_username,
            "ip归属": reply.get('ip_label', '未知') or '未知',
        }
    except Exception as e:
        cid = reply.get('cid', 'N/A')
        logger.warning("跳过回复 #%d (cid=%s): %s | raw=%s",
                       index, cid, e, json.dumps(reply, ensure_ascii=False)[:300])
        return None


def save_replies_and_progress(replies: list, output_file: str, progress_file: str, comment_id: str) -> bool:
    """
    保存爬取到的回复数据到文件，同时更新进度文件。
    只有当回复数据成功保存到文件时，才更新进度文件。
    """
    global buffer

    if not replies:
        with open(progress_file, "a") as f:
            f.write(comment_id + "\n")
        return False

    # 收集数据到缓冲区
    for i, c in enumerate(replies):
        record = _safe_extract_reply(c, i)
        if record is not None:
            buffer.append(record)
        else:
            logger.warning("回复数据不完整，已跳过 (comment_id=%s, reply_index=%d)", comment_id, i)

    # 如果缓冲区数据达到批量保存的阈值，保存到文件
    if len(buffer) >= batch_size:
        df = pd.DataFrame(buffer)
        buffer.clear()  # 清空缓冲区

        if os.path.exists(output_file):
            existing_data = pd.read_csv(output_file)
            df = pd.concat([existing_data, df]).drop_duplicates(subset=["评论ID"])
        df.to_csv(output_file, mode='w', index=False)

        # 同时更新进度文件
        with open(progress_file, "a") as f:
            f.write(comment_id + "\n")

        return True

    return False


def finalize_buffer_and_progress(output_file: str, progress_file: str, comment_id_list: list):
    """
    在程序结束时，将缓冲区剩余的回复数据写入文件，同时写入进度文件。
    """
    global buffer

    if buffer:
        df = pd.DataFrame(buffer)
        buffer.clear()  # 清空缓冲区

        if os.path.exists(output_file):
            existing_data = pd.read_csv(output_file)
            df = pd.concat([existing_data, df]).drop_duplicates(subset=["评论ID"])
        df.to_csv(output_file, mode='w', index=False)

    if comment_id_list:
        with open(progress_file, "a") as f:
            f.write("\n".join(comment_id_list) + "\n")
        comment_id_list.clear()


def load_progress(filename: str) -> set:
    """加载已完成的评论ID"""
    if not os.path.exists(filename):
        return set()
    with open(filename, "r") as f:
        return set(line.strip() for line in f)


async def main():
    async with httpx.AsyncClient(timeout=600, http2=True) as client:
        semaphore = asyncio.Semaphore(50)
        pending_progress = []
        with tqdm(total=total_comments, desc="Fetching replies", unit="comment", initial=completed_comments) as pbar:
            for _, comment in comments_to_process.iterrows():
                comment_id = comment["评论ID"]
                replies = await fetch_replies_for_comment(client, semaphore, comment_id, pbar)
                success = save_replies_and_progress(replies, output_file, progress_file, comment_id)
                if success:
                    pending_progress.append(comment_id)
        finalize_buffer_and_progress(output_file, progress_file, pending_progress)
    print(f"Replies and progress saved to {output_file} and {progress_file}")



buffer = []
batch_size = 10
aweme_id = input("Enter the aweme_id: ")
base_dir = f"data/{aweme_id}"
os.makedirs(base_dir, exist_ok=True)
comments_file = os.path.join(base_dir, "comments.csv")
progress_file = os.path.join(base_dir, "replies_progress.txt")
output_file = os.path.join(base_dir, "replies.csv")

# 加载评论数据和已完成的评论ID
comments = pd.read_csv(comments_file)
processed_cids = load_progress(progress_file)
comments["评论ID"] = comments["评论ID"].astype(str)
processed_cids = set(str(cid) for cid in processed_cids)
comments_to_process = comments[~comments["评论ID"].isin(processed_cids)]
total_comments = len(comments)
completed_comments = len(processed_cids)

print(f"{len(comments_to_process)} comments to process.")
print(f"{completed_comments} comments already processed.")
asyncio.run(main())
