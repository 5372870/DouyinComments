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

with open("cookie.txt", "r") as f:
    cookie = f.readline().strip()


def build_skip_record(index: int, raw_data: dict[str, Any], missing_fields: list[str], reason: str) -> dict[str, Any]:
    return {
        "类型": "评论",
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


def process_comments(comments: list[dict[str, Any]]) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    data: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for index, comment in enumerate(comments):
        comment_id = comment.get("cid")
        if not comment_id:
            skipped.append(build_skip_record(index, comment, ["cid"], "缺少评论ID，无法保存评论"))
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


def save(data: pd.DataFrame, filename: str):
    data.to_csv(filename, index=False)


def save_skipped(skipped: list[dict[str, Any]], filename: str):
    with open(filename, "w", encoding="utf-8") as f:
        json.dump(skipped, f, ensure_ascii=False, indent=2)


async def main():
    aweme_id = input("Enter the aweme_id: ")
    all_comments = await fetch_all_comments_async(aweme_id)
    print(f"Found {len(all_comments)} comments.")
    comments_df, skipped_comments = process_comments(all_comments)
    base_dir = f"data/{aweme_id}"
    os.makedirs(base_dir, exist_ok=True)
    comments_file = os.path.join(base_dir, "comments.csv")
    save(comments_df, comments_file)
    if skipped_comments:
        save_skipped(skipped_comments, os.path.join(base_dir, "skipped_comments.json"))
        print(f"Skipped {len(skipped_comments)} comments with missing required fields.")
    print("Comments saved to comments.csv")


if __name__ == "__main__":
    asyncio.run(main())
