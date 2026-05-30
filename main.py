import asyncio
from datetime import datetime
from typing import Any
import os
import httpx
import pandas as pd
from tqdm import tqdm
from common import common
import logging
import json

url = "https://www.douyin.com/aweme/v1/web/comment/list/"
reply_url = url + "reply/"

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('douyin_comments.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

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
        logger.error("Response is not valid JSON, cookies might be expired or invalid")
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
        try:
            return response.json()
        except ValueError:
            logger.error(f"Response for reply comment {comment_id} is not valid JSON")
            return {}


async def fetch_replies_for_comment(client: httpx.AsyncClient, semaphore, comment: dict, pbar: tqdm) -> list:
    try:
        comment_id = comment.get("cid")
        if not comment_id:
            logger.warning("Comment missing 'cid' field, skipping")
            return []
        has_more = 1
        cursor = 0
        all_replies = []
        reply_total = comment.get("reply_comment_total", 0)
        while has_more and reply_total > 0:
            response = await get_replies_async(client, semaphore, comment_id, cursor=str(cursor))
            replies = response.get("comments", [])
            if isinstance(replies, list):
                all_replies.extend(replies)
            has_more = response.get("has_more", 0)
            if has_more:
                cursor = response.get("cursor", 0)
            await asyncio.sleep(0.5)
        return all_replies
    except Exception as e:
        logger.error(f"Error fetching replies for comment: {e}")
        return []
    finally:
        pbar.update(1)


async def fetch_all_replies_async(comments: list) -> list:
    all_replies = []
    async with httpx.AsyncClient(timeout=600) as client:
        semaphore = asyncio.Semaphore(10)
        with tqdm(total=len(comments), desc="Fetching replies", unit="comment") as pbar:
            tasks = [fetch_replies_for_comment(client, semaphore, comment, pbar) for comment in comments]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"Error in fetching replies: {result}")
                elif isinstance(result, list):
                    all_replies.extend(result)
    return all_replies


def process_comments(comments: list[dict[str, Any]]) -> tuple[pd.DataFrame, list]:
    data = []
    skipped = []
    for idx, c in enumerate(comments):
        try:
            user = c.get('user', {})
            comment_data = {
                "评论ID": c.get('cid', f'unknown_{idx}'),
                "评论内容": c.get('text', ''),
                "评论图片": None,
                "点赞数": c.get('digg_count', 0),
                "评论时间": datetime.fromtimestamp(c.get('create_time', 0)).strftime('%Y-%m-%d %H:%M:%S') if c.get('create_time') else '',
                "用户昵称": user.get('nickname', '未知'),
                "用户主页链接": f"https://www.douyin.com/user/{user.get('sec_uid', '')}" if user.get('sec_uid') else '',
                "用户抖音号": user.get('unique_id', '未知'),
                "用户签名": user.get('signature', '未知'),
                "回复总数": c.get('reply_comment_total', 0),
                "ip归属": c.get('ip_label', '未知')
            }
            
            image_list = c.get('image_list', [])
            if image_list and len(image_list) > 0:
                try:
                    comment_data["评论图片"] = image_list[0].get('origin_url', {}).get('url_list', [None])[0]
                except Exception as e:
                    logger.debug(f"Error parsing image list: {e}")
            
            data.append(comment_data)
        except Exception as e:
            logger.error(f"Error processing comment {idx}: {e}")
            skipped.append({
                'index': idx,
                'raw_data': c,
                'error': str(e)
            })
    
    return pd.DataFrame(data), skipped


def process_replies(replies: list[dict[str, Any]], comments: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    data = []
    skipped = []
    comment_nickname_map = dict(zip(comments['评论ID'], comments['用户昵称']))
    
    for idx, c in enumerate(replies):
        try:
            user = c.get('user', {})
            reply_id = c.get('reply_id', '')
            reply_to_reply_id = c.get('reply_to_reply_id', '0')
            
            reply_data = {
                "评论ID": c.get('cid', f'unknown_{idx}'),
                "评论内容": c.get('text', ''),
                "评论图片": None,
                "点赞数": c.get('digg_count', 0),
                "评论时间": datetime.fromtimestamp(c.get('create_time', 0)).strftime('%Y-%m-%d %H:%M:%S') if c.get('create_time') else '',
                "用户昵称": user.get('nickname', '未知'),
                "用户主页链接": f"https://www.douyin.com/user/{user.get('sec_uid', '')}" if user.get('sec_uid') else '',
                "用户抖音号": user.get('unique_id', '未知'),
                "用户签名": user.get('signature', '未知'),
                "回复的评论": reply_id,
                "具体的回复对象": reply_to_reply_id if reply_to_reply_id != "0" else reply_id,
                "回复给谁": comment_nickname_map.get(reply_id, c.get('reply_to_username', '未知')) if reply_to_reply_id == "0" else c.get('reply_to_username', '未知'),
                "ip归属": c.get('ip_label', '未知')
            }
            
            image_list = c.get('image_list', [])
            if image_list and len(image_list) > 0:
                try:
                    reply_data["评论图片"] = image_list[0].get('origin_url', {}).get('url_list', [None])[0]
                except Exception as e:
                    logger.debug(f"Error parsing reply image list: {e}")
            
            data.append(reply_data)
        except Exception as e:
            logger.error(f"Error processing reply {idx}: {e}")
            skipped.append({
                'index': idx,
                'raw_data': c,
                'error': str(e)
            })
    
    return pd.DataFrame(data), skipped


def save(data: pd.DataFrame, filename: str):
    data.to_csv(filename, index=False)


def save_skipped(skipped: list, filename: str):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(skipped, f, ensure_ascii=False, indent=2)


async def main():
    base_dir = f"data/v1/{aweme_id}"
    os.makedirs(base_dir, exist_ok=True)
    
    try:
        all_comments = await fetch_all_comments_async(aweme_id)
        logger.info(f"Found {len(all_comments)} comments.")
    except Exception as e:
        logger.error(f"Error fetching comments: {e}")
        return
    
    try:
        all_comments_df, skipped_comments = process_comments(all_comments)
        comments_file = os.path.join(base_dir, "comments.csv")
        save(all_comments_df, comments_file)
        logger.info(f"Saved {len(all_comments_df)} comments to {comments_file}")
        
        if skipped_comments:
            skipped_comments_file = os.path.join(base_dir, "skipped_comments.json")
            save_skipped(skipped_comments, skipped_comments_file)
            logger.warning(f"Skipped {len(skipped_comments)} comments, saved to {skipped_comments_file}")
    except Exception as e:
        logger.error(f"Error processing comments: {e}")
        return
    
    try:
        all_replies = await fetch_all_replies_async(all_comments)
        logger.info(f"Found {len(all_replies)} replies")
        logger.info(f"Found {len(all_replies) + len(all_comments)} in totals")
    except Exception as e:
        logger.error(f"Error fetching replies: {e}")
        return
    
    try:
        all_replies_df, skipped_replies = process_replies(all_replies, all_comments_df)
        replies_file = os.path.join(base_dir, "replies.csv")
        save(all_replies_df, replies_file)
        logger.info(f"Saved {len(all_replies_df)} replies to {replies_file}")
        
        if skipped_replies:
            skipped_replies_file = os.path.join(base_dir, "skipped_replies.json")
            save_skipped(skipped_replies, skipped_replies_file)
            logger.warning(f"Skipped {len(skipped_replies)} replies, saved to {skipped_replies_file}")
    except Exception as e:
        logger.error(f"Error processing replies: {e}")
        return


if __name__ == "__main__":
    try:
        asyncio.run(main())
        logger.info('done!')
    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
