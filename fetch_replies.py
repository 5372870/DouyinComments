import asyncio
import json
import os
from datetime import datetime
from typing import Any

import httpx
import pandas as pd
from tqdm import tqdm

from common import common

reply_url = "https://www.douyin.com/aweme/v1/web/comment/list/reply/"

with open("cookie.txt", "r") as f:
    cookie = f.readline().strip()


buffer: list[dict[str, Any]] = []
skipped_buffer: list[dict[str, Any]] = []
progress_buffer: list[str] = []
batch_size = 10


def build_skip_record(index: int, raw_data: dict[str, Any], missing_fields: list[str], reason: str) -> dict[str, Any]:
    return {
        "类型": "回复",
        "索引": index,
        "缺失字段": missing_fields,
        "原因": reason,
        "原始数据": raw_data,
    }


def get_user_data(item: dict[str, Any]) -> dict[str, Any]:
    user = item.get("user")
    return user if isinstance(user, dict) else {}


def get_image_url(item: dict[str, Any]) -> str | None:
    image_list = item.get("image_list")
    if not isinstance(image_list, list) or not image_list:
        return None

    first_image = image_list[0]
    if not isinstance(first_image, dict):
        return None

    origin_url = first_image.get("origin_url")
    if not isinstance(origin_url, dict):
        return None

    url_list = origin_url.get("url_list")
    if not isinstance(url_list, list) or not url_list:
        return None

    first_url = url_list[0]
    return first_url if isinstance(first_url, str) else None


def format_timestamp(timestamp: Any) -> str:
    if timestamp in (None, ""):
        return ""

    try:
        return datetime.fromtimestamp(int(timestamp)).strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError, OSError):
        return ""


def normalize_reply(reply: dict[str, Any], index: int) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    missing_fields = [field for field in ("cid", "reply_id") if not reply.get(field)]
    if missing_fields:
        return None, build_skip_record(index, reply, missing_fields, "缺少必要字段，无法建立回复关系")

    user = get_user_data(reply)
    sec_uid = user.get("sec_uid")
    reply_id = str(reply.get("reply_id"))
    reply_to_reply_id = str(reply.get("reply_to_reply_id", "0"))

    data = {
        "评论ID": str(reply.get("cid")),
        "评论内容": reply.get("text", ""),
        "评论图片": get_image_url(reply),
        "点赞数": reply.get("digg_count", 0),
        "评论时间": format_timestamp(reply.get("create_time")),
        "用户昵称": user.get("nickname", "未知"),
        "用户主页链接": f"https://www.douyin.com/user/{sec_uid}" if sec_uid else "",
        "用户抖音号": user.get("unique_id", "未知"),
        "用户签名": user.get("signature", "未知"),
        "回复的评论ID": reply_id,
        "具体的回复对象": reply_to_reply_id if reply_to_reply_id != "0" else reply_id,
        "回复给谁": reply.get("reply_to_username", "未知"),
        "ip归属": reply.get("ip_label", "未知"),
    }
    return data, None


def write_skipped_records(skipped_file: str):
    if not skipped_buffer:
        return

    existing_records: list[dict[str, Any]] = []
    if os.path.exists(skipped_file):
        with open(skipped_file, "r", encoding="utf-8") as f:
            try:
                loaded = json.load(f)
                if isinstance(loaded, list):
                    existing_records = loaded
            except json.JSONDecodeError:
                existing_records = []

    with open(skipped_file, "w", encoding="utf-8") as f:
        json.dump(existing_records + skipped_buffer, f, ensure_ascii=False, indent=2)

    skipped_buffer.clear()


def flush_buffer(output_file: str, progress_file: str, skipped_file: str):
    if buffer:
        df = pd.DataFrame(buffer)
        buffer.clear()

        if os.path.exists(output_file):
            existing_data = pd.read_csv(output_file)
            df = pd.concat([existing_data, df]).drop_duplicates(subset=["评论ID"])
        df.to_csv(output_file, mode="w", index=False)

    if progress_buffer:
        with open(progress_file, "a") as f:
            f.write("\n".join(progress_buffer) + "\n")
        progress_buffer.clear()

    write_skipped_records(skipped_file)


async def get_replies_async(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    comment_id: str,
    cursor: str = "0",
    count: str = "50",
) -> dict:
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


def save_replies_and_progress(
    replies: list[dict[str, Any]],
    output_file: str,
    progress_file: str,
    skipped_file: str,
    comment_id: str,
):
    valid_rows: list[dict[str, Any]] = []

    for index, reply in enumerate(replies):
        normalized_reply, skipped_reply = normalize_reply(reply, index)
        if normalized_reply:
            valid_rows.append(normalized_reply)
        if skipped_reply:
            skipped_buffer.append(skipped_reply)

    buffer.extend(valid_rows)
    progress_buffer.append(str(comment_id))

    if len(buffer) >= batch_size:
        flush_buffer(output_file, progress_file, skipped_file)


def finalize_buffer_and_progress(output_file: str, progress_file: str, skipped_file: str):
    flush_buffer(output_file, progress_file, skipped_file)


def load_progress(filename: str) -> set:
    if not os.path.exists(filename):
        return set()
    with open(filename, "r") as f:
        return set(line.strip() for line in f)


async def main():
    async with httpx.AsyncClient(timeout=600, http2=True) as client:
        semaphore = asyncio.Semaphore(50)
        with tqdm(total=total_comments, desc="Fetching replies", unit="comment", initial=completed_comments) as pbar:
            for _, comment in comments_to_process.iterrows():
                comment_id = comment["评论ID"]
                replies = await fetch_replies_for_comment(client, semaphore, comment_id, pbar)
                save_replies_and_progress(replies, output_file, progress_file, skipped_file, comment_id)
        finalize_buffer_and_progress(output_file, progress_file, skipped_file)
    print(f"Replies and progress saved to {output_file} and {progress_file}")
    if os.path.exists(skipped_file):
        print(f"Skipped replies saved to {skipped_file}")


aweme_id = input("Enter the aweme_id: ")
base_dir = f"data/{aweme_id}"
os.makedirs(base_dir, exist_ok=True)
comments_file = os.path.join(base_dir, "comments.csv")
progress_file = os.path.join(base_dir, "replies_progress.txt")
output_file = os.path.join(base_dir, "replies.csv")
skipped_file = os.path.join(base_dir, "skipped_replies.json")

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
