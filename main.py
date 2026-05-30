import asyncio
import json
import os
from datetime import datetime
from typing import Any

import httpx
import pandas as pd
from tqdm import tqdm

from common import common

url = "https://www.douyin.com/aweme/v1/web/comment/list/"
reply_url = url + "reply/"

with open("cookie.txt", "r") as f:
    cookie = f.readline().strip()

aweme_id = input("Enter the aweme_id: ")


def build_skip_record(item_type: str, index: int | None, raw_data: dict[str, Any], missing_fields: list[str], reason: str) -> dict[str, Any]:
    return {
        "类型": item_type,
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


async def get_comments_async(
    client: httpx.AsyncClient,
    aweme_id: str,
    cursor: str = "0",
    count: str = "50",
) -> dict[str, Any]:
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
        all_comments: list[dict[str, Any]] = []
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


async def get_replies_async(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    comment_id: str,
    cursor: str = "0",
    count: str = "50",
) -> dict[str, Any]:
    params = {"cursor": cursor, "count": count, "item_type": 0, "item_id": aweme_id, "comment_id": comment_id}
    headers = {"cookie": cookie}
    params, headers = common(reply_url, params, headers)
    async with semaphore:
        response = await client.get(reply_url, params=params, headers=headers)
        await asyncio.sleep(0.3)
        try:
            return response.json()
        except ValueError:
            return {}


async def fetch_replies_for_comment(
    client: httpx.AsyncClient,
    semaphore: asyncio.Semaphore,
    comment: dict[str, Any],
    pbar: tqdm,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    comment_id = comment.get("cid")
    if not comment_id:
        pbar.update(1)
        return [], [build_skip_record("回复抓取目标", None, comment, ["cid"], "缺少评论ID，无法抓取该评论的回复")]

    reply_total = comment.get("reply_comment_total")
    try:
        if reply_total is not None and int(reply_total) <= 0:
            pbar.update(1)
            return [], []
    except (TypeError, ValueError):
        pass

    has_more = 1
    cursor = 0
    all_replies: list[dict[str, Any]] = []
    while has_more:
        response = await get_replies_async(client, semaphore, str(comment_id), cursor=str(cursor))
        replies = response.get("comments", [])
        if isinstance(replies, list):
            all_replies.extend(replies)
        has_more = response.get("has_more", 0)
        if has_more:
            cursor = response.get("cursor", 0)
        await asyncio.sleep(0.5)
    pbar.update(1)
    return all_replies, []


async def fetch_all_replies_async(comments: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    all_replies: list[dict[str, Any]] = []
    skipped_targets: list[dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=600) as client:
        semaphore = asyncio.Semaphore(10)
        with tqdm(total=len(comments), desc="Fetching replies", unit="comment") as pbar:
            tasks = [fetch_replies_for_comment(client, semaphore, comment, pbar) for comment in comments]
            results = await asyncio.gather(*tasks)
            for replies, skipped in results:
                all_replies.extend(replies)
                skipped_targets.extend(skipped)
    return all_replies, skipped_targets


def process_comments(comments: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    data: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for index, comment in enumerate(comments):
        comment_id = comment.get("cid")
        if not comment_id:
            skipped.append(build_skip_record("评论", index, comment, ["cid"], "缺少评论ID，无法保存评论"))
            continue

        user = get_user_data(comment)
        sec_uid = user.get("sec_uid")
        data.append(
            {
                "评论ID": str(comment_id),
                "评论内容": comment.get("text", ""),
                "评论图片": get_image_url(comment),
                "点赞数": comment.get("digg_count", 0),
                "评论时间": format_timestamp(comment.get("create_time")),
                "用户昵称": user.get("nickname", "未知"),
                "用户主页链接": f"https://www.douyin.com/user/{sec_uid}" if sec_uid else "",
                "用户抖音号": user.get("unique_id", "未知"),
                "用户签名": user.get("signature", "未知"),
                "回复总数": comment.get("reply_comment_total", 0),
                "ip归属": comment.get("ip_label", "未知"),
            }
        )

    return pd.DataFrame(data), skipped


def process_replies(
    replies: list[dict[str, Any]], comments: pd.DataFrame
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    data: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    comment_nickname_map = {
        str(comment_id): nickname
        for comment_id, nickname in zip(comments.get("评论ID", pd.Series(dtype=str)), comments.get("用户昵称", pd.Series(dtype=str)))
    }

    for index, reply in enumerate(replies):
        missing_fields = [field for field in ("cid", "reply_id") if not reply.get(field)]
        if missing_fields:
            skipped.append(build_skip_record("回复", index, reply, missing_fields, "缺少必要字段，无法建立回复关系"))
            continue

        user = get_user_data(reply)
        sec_uid = user.get("sec_uid")
        reply_id = str(reply.get("reply_id"))
        reply_to_reply_id = str(reply.get("reply_to_reply_id", "0"))

        if reply_to_reply_id == "0":
            reply_target = comment_nickname_map.get(reply_id, "未知")
        else:
            reply_target = reply.get("reply_to_username", "未知")

        data.append(
            {
                "评论ID": str(reply.get("cid")),
                "评论内容": reply.get("text", ""),
                "评论图片": get_image_url(reply),
                "点赞数": reply.get("digg_count", 0),
                "评论时间": format_timestamp(reply.get("create_time")),
                "用户昵称": user.get("nickname", "未知"),
                "用户主页链接": f"https://www.douyin.com/user/{sec_uid}" if sec_uid else "",
                "用户抖音号": user.get("unique_id", "未知"),
                "用户签名": user.get("signature", "未知"),
                "回复的评论": reply_id,
                "具体的回复对象": reply_to_reply_id if reply_to_reply_id != "0" else reply_id,
                "回复给谁": reply_target,
                "ip归属": reply.get("ip_label", "未知"),
            }
        )

    return pd.DataFrame(data), skipped


def save(data: pd.DataFrame, filename: str):
    data.to_csv(filename, index=False)


def save_skipped(skipped: list[dict[str, Any]], filename: str):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(skipped, f, ensure_ascii=False, indent=2)


async def main():
    base_dir = f"data/v1/{aweme_id}"
    os.makedirs(base_dir, exist_ok=True)

    all_comments = await fetch_all_comments_async(aweme_id)
    print(f"Found {len(all_comments)} comments.")

    processed_comments, skipped_comments = process_comments(all_comments)
    comments_file = os.path.join(base_dir, "comments.csv")
    save(processed_comments, comments_file)
    if skipped_comments:
        save_skipped(skipped_comments, os.path.join(base_dir, "skipped_comments.json"))
        print(f"Skipped {len(skipped_comments)} comments with missing required fields.")

    all_replies, skipped_reply_targets = await fetch_all_replies_async(all_comments)
    print(f"Found {len(all_replies)} replies")
    print(f"Found {len(all_replies) + len(all_comments)} in totals")

    if skipped_reply_targets:
        save_skipped(skipped_reply_targets, os.path.join(base_dir, "skipped_reply_targets.json"))
        print(f"Skipped reply fetching for {len(skipped_reply_targets)} comments with missing required fields.")

    processed_replies, skipped_replies = process_replies(all_replies, processed_comments)
    replies_file = os.path.join(base_dir, "replies.csv")
    save(processed_replies, replies_file)
    if skipped_replies:
        save_skipped(skipped_replies, os.path.join(base_dir, "skipped_replies.json"))
        print(f"Skipped {len(skipped_replies)} replies with missing required fields.")


if __name__ == "__main__":
    asyncio.run(main())
    print("done!")
