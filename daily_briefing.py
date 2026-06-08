# 每日 AI 简报 — 自动抓取 + 大模型总结 + 推送

import feedparser
import requests
import json
import os
from datetime import datetime
from typing import Optional

# ============================================================
# 配置区 —— 按你的实际情况修改
# ============================================================

# 大模型 API（兼容 OpenAI 格式，也可用 DeepSeek / 通义千问 / Kimi 等）
LLM_API_KEY  = os.environ.get("LLM_API_KEY", "sk-your-api-key-here")
LLM_API_URL  = os.environ.get("LLM_API_URL", "https://api.deepseek.com/v1/chat/completions")
LLM_MODEL    = os.environ.get("LLM_MODEL", "deepseek-chat")

# RSS 源列表
RSS_SOURCES = [
    "https://www.zhihu.com/rss",
    "https://sspai.com/feed",
    "https://hnrss.org/frontpage",
]

# 取前 N 篇文章
TOP_N = 3

# 推送方式（飞书 / 钉钉 / Server酱），留空则不推送
FEISHU_WEBHOOK  = os.environ.get("FEISHU_WEBHOOK", "")
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "")
SERVER_CHAN_KEY  = os.environ.get("SERVER_CHAN_KEY", "")

# 是否用 newspaper3k 提取正文（需要额外安装：pip install newspaper3k）
USE_FULL_TEXT = False

# ============================================================
# 正文提取（可选）
# ============================================================

def extract_full_text(url: str) -> Optional[str]:
    """用 newspaper3k 提取网页正文，失败则返回 None"""
    if not USE_FULL_TEXT:
        return None
    try:
        from newspaper import Article
        article = Article(url)
        article.download()
        article.parse()
        text = article.text.strip()
        return text[:3000] if len(text) > 100 else None
    except Exception:
        return None


# ============================================================
# RSS 抓取
# ============================================================

def fetch_feeds() -> list[dict]:
    """抓取所有 RSS 源，合并、去重、按时间倒序、取 TOP_N"""
    all_items = []

    for url in RSS_SOURCES:
        try:
            feed = feedparser.parse(url)
            source_name = feed.feed.get("title", url)
            for entry in feed.entries:
                all_items.append({
                    "title": entry.get("title", "").strip(),
                    "link": entry.get("link", ""),
                    "summary": (entry.get("summary") or entry.get("description") or "").strip(),
                    "published": entry.get("published", entry.get("updated", "")),
                    "source": source_name,
                })
        except Exception as e:
            print(f"[WARN] 抓取失败 {url}: {e}")

    # 按发布时间倒序
    all_items.sort(key=lambda x: x["published"], reverse=True)

    # 去重（按标题）
    seen = set()
    unique = []
    for item in all_items:
        if item["title"] not in seen:
            seen.add(item["title"])
            unique.append(item)

    return unique[:TOP_N]


# ============================================================
# 大模型总结
# ============================================================

def summarize(article: dict) -> str:
    """调用大模型生成 200 字以内的核心观点总结"""
    content = article.get("summary", "")

    # 可选：提取正文替代摘要
    if USE_FULL_TEXT and article.get("link"):
        full = extract_full_text(article["link"])
        if full:
            content = full

    # 如果没有内容，跳过
    if not content or len(content) < 20:
        return "（内容过短，无法总结）"

    system_prompt = (
        "你是一个专业的科技新闻编辑。请用 200 字以内总结以下文章的核心观点。"
        "直接给出摘要，不要加'这篇文章讲述了'之类的引导语。"
        "如果文章是英文，请用中文总结。"
    )

    user_prompt = f"标题：{article['title']}\n\n内容：{content[:4000]}"

    headers = {
        "Authorization": f"Bearer {LLM_API_KEY}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": LLM_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.5,
        "max_tokens": 400,
    }

    try:
        resp = requests.post(LLM_API_URL, headers=headers, json=payload, timeout=30)
        if resp.status_code == 200:
            return resp.json()["choices"][0]["message"]["content"].strip()
        else:
            print(f"[WARN] LLM 返回错误 {resp.status_code}: {resp.text[:200]}")
            return f"（API 错误: {resp.status_code}）"
    except Exception as e:
        print(f"[WARN] LLM 调用失败: {e}")
        return "（大模型暂时不可用）"


# ============================================================
# 格式化输出
# ============================================================

def format_message(articles: list[dict], summaries: list[str]) -> str:
    """组装最终推送消息"""
    today = datetime.now().strftime("%Y年%m月%d日")
    lines = [f"📰 **每日 AI 简报** — {today}\n"]

    for i, (article, summary) in enumerate(zip(articles, summaries), 1):
        source = article.get("source", "未知来源")
        lines.append(f"### {i}. {article['title']}")
        lines.append(f"📌 来源：{source}")
        lines.append(f"{summary}")
        lines.append(f"🔗 {article['link']}\n")

    lines.append(f"———\n⏰ 生成时间：{datetime.now().strftime('%H:%M:%S')}")
    return "\n".join(lines)


# ============================================================
# 推送通知
# ============================================================

def send_feishu(message: str):
    """发送到飞书群机器人"""
    if not FEISHU_WEBHOOK:
        return
    payload = {"msg_type": "interactive", "card": {
        "header": {"title": {"content": "每日 AI 简报", "tag": "plain_text"}},
        "elements": [{"tag": "markdown", "content": message}]
    }}
    try:
        resp = requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
        print(f"[飞书] 发送{'成功' if resp.status_code==200 else '失败'}: {resp.status_code}")
    except Exception as e:
        print(f"[飞书] 发送异常: {e}")


def send_dingtalk(message: str):
    """发送到钉钉群机器人"""
    if not DINGTALK_WEBHOOK:
        return
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": "每日 AI 简报", "text": message}
    }
    try:
        resp = requests.post(DINGTALK_WEBHOOK, json=payload, timeout=10)
        print(f"[钉钉] 发送{'成功' if resp.status_code==200 else '失败'}: {resp.status_code}")
    except Exception as e:
        print(f"[钉钉] 发送异常: {e}")


def send_serverchan(message: str):
    """通过 Server酱 推送到微信"""
    if not SERVER_CHAN_KEY:
        return
    url = f"https://sctapi.ftqq.com/{SERVER_CHAN_KEY}.send"
    payload = {"title": "每日 AI 简报", "desp": message.replace("\n", "\n\n")}
    try:
        resp = requests.post(url, data=payload, timeout=10)
        print(f"[Server酱] 发送{'成功' if resp.status_code==200 else '失败'}")
    except Exception as e:
        print(f"[Server酱] 发送异常: {e}")


# ============================================================
# 主流程
# ============================================================

def main():
    print("=" * 50)
    print(f"🚀 每日 AI 简报 — 开始运行 {datetime.now()}")
    print("=" * 50)

    # Step 1: 抓取
    print("\n📡 正在抓取 RSS...")
    articles = fetch_feeds()
    print(f"✅ 获取 {len(articles)} 篇文章")
    for a in articles:
        print(f"   - [{a['source']}] {a['title'][:40]}...")

    if not articles:
        print("❌ 没有抓取到任何文章，退出。")
        return

    # Step 2: 总结
    print("\n🤖 正在调用大模型总结...")
    summaries = []
    for i, article in enumerate(articles, 1):
        print(f"   总结第 {i} 篇: {article['title'][:30]}...")
        summary = summarize(article)
        summaries.append(summary)

    # Step 3: 格式化
    message = format_message(articles, summaries)
    print("\n📝 生成简报：\n")
    print(message)

    # Step 4: 推送
    print("\n📤 推送通知...")
    send_feishu(message)
    send_dingtalk(message)
    send_serverchan(message)

    print("\n✅ 全部完成！")


if __name__ == "__main__":
    main()
