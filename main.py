import asyncio
import json
from datetime import datetime
from typing import Any
import os
import httpx
import pandas as pd
from tqdm import tqdm
from common import common

url = "https://www.douyin.com/aweme/v1/web/comment/list/"
reply_url = url + "reply/"

with open('cookie.txt','r') as f:
    cookie = f.readline().strip()

aweme_id = input("Enter the aweme_id: ")

async def get_comments_async(client: httpx.AsyncClient, aweme_id: str, cursor: str = "0", count: str = "50") -> dict[
    str, Any]:
    params = {"aweme_id": aweme_id, "cursor": cursor, "count": count, "item_type": 0}
    headers = {"cookie": cookie}
    params, headers = common(url, params, headers)
    response = await client.get(url, params=params, headers=headers)
    await asyncio.sleep(0.8)
    try:
        return response.json()
    except ValueError:
        # Return an empty dictionary if the response is not valid JSON.
        # Alternatively, you could raise an exception here to indicate that the cookies might be expired or invalid.
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


async def get_replies_async(client: httpx.AsyncClient, semaphore, comment_id: str, cursor: str = "0",
                            count: str = "50") -> dict:
    params = {"cursor": cursor, "count": count, "item_type": 0, "item_id": aweme_id, "comment_id": comment_id}
    headers = {"cookie": cookie}
    params, headers = common(reply_url, params, headers)
    async with semaphore:
        response = await client.get(reply_url, params=params, headers=headers)
        await asyncio.sleep(0.3)
        # print(response.text)
        try:
            return response.json()
        except ValueError:
            # Return an empty dictionary if the response is not valid JSON.
            # Alternatively, you could raise an exception here to indicate that the cookies might be expired or invalid.
            return {}


async def fetch_replies_for_comment(client: httpx.AsyncClient, semaphore, comment: dict, pbar: tqdm) -> list:
    comment_id = comment["cid"]
    has_more = 1
    cursor = 0
    all_replies = []
    while has_more and comment["reply_comment_total"] > 0:
        response = await get_replies_async(client, semaphore, comment_id, cursor=str(cursor))
        replies = response.get("comments", [])
        if isinstance(replies, list):
            all_replies.extend(replies)
        has_more = response.get("has_more", 0)
        if has_more:
            cursor = response.get("cursor", 0)
        await asyncio.sleep(0.5)
    pbar.update(1)
    return all_replies


async def fetch_all_replies_async(comments: list) -> list:
    all_replies = []
    async with httpx.AsyncClient(timeout=600) as client:
        semaphore = asyncio.Semaphore(10)  # 在这里创建信号量
        with tqdm(total=len(comments), desc="Fetching replies", unit="comment") as pbar:
            tasks = [fetch_replies_for_comment(client, semaphore, comment, pbar) for comment in comments]
            results = await asyncio.gather(*tasks)
            for result in results:
                all_replies.extend(result)
    return all_replies


def process_comments(comments: list[dict[str, Any]]) -> tuple[pd.DataFrame, list]:
    data = []
    skipped = []
    for c in comments:
        try:
            user = c.get('user') or {}
            
            image_url = None
            if c.get('image_list'):
                try:
                    image_url = c['image_list'][0]['origin_url']['url_list'][0]
                except (KeyError, IndexError, TypeError):
                    pass
            
            item = {
                "评论ID": c['cid'],
                "评论内容": c.get('text', ''),
                "评论图片": image_url,
                "点赞数": c.get('digg_count', 0),
                "评论时间": datetime.fromtimestamp(c.get('create_time', 0)).strftime('%Y-%m-%d %H:%M:%S'),
                "用户昵称": user['nickname'],
                "用户主页链接": f"https://www.douyin.com/user/{user['sec_uid']}" if user.get('sec_uid') else '',
                "用户抖音号": user.get('unique_id', '未知'),
                "用户签名": user.get('signature', '未知'),
                "回复总数": c.get('reply_comment_total', 0),
                "ip归属": c.get('ip_label', '未知')
            }
            data.append(item)
        except KeyError as e:
            skipped.append({"error": f"Missing key: {e}", "raw_data": c})
        except Exception as e:
            skipped.append({"error": str(e), "raw_data": c})
            
    return pd.DataFrame(data), skipped


def process_replies(replies: list[dict[str, Any]], comments: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    data = []
    skipped = []
    
    comment_nickname_map = {}
    if not comments.empty and '评论ID' in comments.columns and '用户昵称' in comments.columns:
        comment_nickname_map = dict(zip(comments['评论ID'], comments['用户昵称']))

    for c in replies:
        try:
            user = c.get('user') or {}
            
            image_url = None
            if c.get('image_list'):
                try:
                    image_url = c['image_list'][0]['origin_url']['url_list'][0]
                except (KeyError, IndexError, TypeError):
                    pass
            
            reply_id = c['reply_id']
            reply_to_reply_id = c.get("reply_to_reply_id", "0")
            
            if reply_to_reply_id == "0":
                reply_to_who = comment_nickname_map.get(reply_id, "未知")
            else:
                reply_to_who = c.get("reply_to_username", "未知")

            item = {
                "评论ID": c["cid"],
                "评论内容": c.get("text", ""),
                "评论图片": image_url,
                "点赞数": c.get("digg_count", 0),
                "评论时间": datetime.fromtimestamp(c.get("create_time", 0)).strftime("%Y-%m-%d %H:%M:%S"),
                "用户昵称": user["nickname"],
                "用户主页链接": f"https://www.douyin.com/user/{user['sec_uid']}" if user.get("sec_uid") else "",
                "用户抖音号": user.get("unique_id", "未知"),
                "用户签名": user.get("signature", "未知"),
                "回复的评论": reply_id,
                "具体的回复对象": reply_to_reply_id if reply_to_reply_id != "0" else reply_id,
                "回复给谁": reply_to_who,
                "ip归属": c.get("ip_label", "未知")
            }
            data.append(item)
        except KeyError as e:
            skipped.append({"error": f"Missing key: {e}", "raw_data": c})
        except Exception as e:
            skipped.append({"error": str(e), "raw_data": c})

    return pd.DataFrame(data), skipped


def save(data: pd.DataFrame, filename: str):
    data.to_csv(filename, index=False)





async def main():
    # 评论部分
    all_comments = await fetch_all_comments_async(aweme_id)
    print(f"Found {len(all_comments)} comments.")
    all_comments_, skipped_comments = process_comments(all_comments)
    base_dir = f"data/v1/{aweme_id}"
    os.makedirs(base_dir, exist_ok=True)
    comments_file = os.path.join(base_dir, "comments.csv")
    save(all_comments_, comments_file)
    if skipped_comments:
        with open(os.path.join(base_dir, "skipped_comments.json"), "w", encoding="utf-8") as f:
            json.dump(skipped_comments, f, ensure_ascii=False, indent=2)
        print(f"Skipped {len(skipped_comments)} comments due to missing fields.")

    # 回复部分 如果不需要直接注释掉
    all_replies = await fetch_all_replies_async(all_comments)
    print(f"Found {len(all_replies)} replies")
    print(f"Found {len(all_replies) + len(all_comments)} in totals")
    all_replies_df, skipped_replies = process_replies(all_replies, all_comments_)
    replies_file = os.path.join(base_dir, "replies.csv")
    save(all_replies_df, replies_file)
    if skipped_replies:
        with open(os.path.join(base_dir, "skipped_replies.json"), "w", encoding="utf-8") as f:
            json.dump(skipped_replies, f, ensure_ascii=False, indent=2)
        print(f"Skipped {len(skipped_replies)} replies due to missing fields.")


# 运行 main 函数
if __name__ == "__main__":
    asyncio.run(main())
    print('done!')
