import asyncio
import logging
import httpx
import pandas as pd
from tqdm import tqdm
import os
from datetime import datetime
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

reply_url = "https://www.douyin.com/aweme/v1/web/comment/list/reply/"

with open('cookie.txt', 'r') as f:
    cookie = f.readline().strip()


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


def _process_single_reply(c: dict) -> dict | None:
    cid = c.get('cid')
    if not cid:
        logger.warning("回复缺少 cid 字段，已跳过: %s", {k: v for k, v in c.items() if k in ('cid', 'text')})
        return None
    reply_id = c.get('reply_id', '')
    reply_to_reply_id = c.get('reply_to_reply_id', '0')
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
        "回复的评论ID": reply_id,
        "具体的回复对象": reply_to_reply_id if reply_to_reply_id != "0" and reply_to_reply_id else reply_id,
        "回复给谁": c.get('reply_to_username'),
        "ip归属": c.get('ip_label', '未知')
    }
    missing = [k for k in ('cid', 'text', 'digg_count', 'create_time', 'user', 'reply_id', 'reply_to_reply_id') if k not in c]
    if missing:
        logger.warning("回复ID=%s 缺少字段: %s", cid, missing)
    return row


def save_replies_and_progress(replies: list, output_file: str, progress_file: str, comment_id: str) -> bool:
    global buffer

    if not replies:
        with open(progress_file, "a") as f:
            f.write(comment_id + "\n")
        return False

    data = []
    skipped = 0
    for c in replies:
        try:
            row = _process_single_reply(c)
            if row is not None:
                data.append(row)
            else:
                skipped += 1
        except Exception as e:
            cid = c.get('cid', '未知')
            logger.warning("回复ID=%s 解析异常，已跳过: %s", cid, e)
            skipped += 1

    if skipped:
        print(f"⚠ 回复处理跳过 {skipped} 条不完整数据（详见 missing_fields.log）")

    buffer.extend(data)

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
