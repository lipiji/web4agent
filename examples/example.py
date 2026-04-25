"""
webweb 使用示例
运行：python example.py
"""

import asyncio
import json

from webweb import (
    agent_read_url,
    agent_read_urls,
    discover_links,
    read_fast,
    read_many,
    read_url,
)

SEP = "─" * 60


# ── 1. 最简单：读一个网页 ──────────────────────────────────────────
async def demo_read_one():
    print(f"\n{SEP}")
    print("【1】read_url — 自动降级策略")
    print(SEP)

    result = await read_url("https://httpbin.org/html", strategy="fast")

    print(f"URL        : {result.url}")
    print(f"标题       : {result.title}")
    print(f"状态码     : {result.status_code}")
    print(f"成功       : {result.success}")
    print(f"策略       : {result.strategy_used}")
    print(f"耗时       : {result.elapsed_ms} ms")
    print(f"正文前200字: {(result.text or '')[:200]!r}")


# ── 2. 指定 fast 策略，查看完整字段 ──────────────────────────────
async def demo_read_fast():
    print(f"\n{SEP}")
    print("【2】read_fast — httpx 直接抓取")
    print(SEP)

    result = await read_fast("https://httpbin.org/html")

    print(f"final_url  : {result.final_url}")
    print(f"有 HTML    : {result.html is not None}")
    print(f"有 Markdown: {result.markdown is not None}")
    print(f"Markdown 前100字: {(result.markdown or '')[:100]!r}")
    if result.attempts:
        a = result.attempts[0]
        print(f"attempt    : strategy={a.strategy}, success={a.success}, elapsed={a.elapsed_ms}ms")


# ── 3. 批量并发抓取 ───────────────────────────────────────────────
async def demo_read_many():
    print(f"\n{SEP}")
    print("【3】read_many — 并发批量抓取")
    print(SEP)

    urls = [
        "https://httpbin.org/html",
        "https://httpbin.org/json",
        "https://httpbin.org/status/404",   # 故意 404
        "https://httpbin.org/delay/1",
        "https://httpbin.org/html",          # 重复 URL，只抓一次
        "https://baike.baidu.com/item/Python/407313",  # 百度百科
        "https://arxiv.org/abs/1706.03762",      # 学术论文摘要
    ]

    results = await read_many(urls, concurrency=3, strategy="fast")

    for r in results:
        status = "OK" if r.success else "FAIL"
        print(f"  [{status}] {r.url:<40} status={r.status_code}  {r.elapsed_ms}ms")

    succeeded = sum(1 for r in results if r.success)
    print(f"\n合计 {len(results)} 条（含重复），成功 {succeeded}，失败 {len(results) - succeeded}")


# ── 4. Agent 接口（精简 dict，适合 LLM context）────────────────────
async def demo_agent():
    print(f"\n{SEP}")
    print("【4】agent_read_url — LLM 友好输出")
    print(SEP)

    r = await agent_read_url("https://httpbin.org/html", strategy="fast")

    # 只打印 key，content 截断显示
    display = {**r, "content": (r["content"] or "")[:200] + "..."}
    print(json.dumps(display, indent=2, ensure_ascii=False))


# ── 5. 批量 Agent 接口 ────────────────────────────────────────────
async def demo_agent_many():
    print(f"\n{SEP}")
    print("【5】agent_read_urls — 批量 Agent 输出")
    print(SEP)

    summary = await agent_read_urls(
        [
            "https://httpbin.org/html",
            "https://httpbin.org/status/500",  # 服务器错误
        ],
        concurrency=2,
        strategy="fast",
    )

    print(f"total={summary['total']}  succeeded={summary['succeeded']}  failed={summary['failed']}")
    for item in summary["results"]:
        status = "OK" if item["success"] else "FAIL"
        print(f"  [{status}] {item['url']}")
        if item["error"]:
            print(f"       error: {item['error']}")
        if item["content"]:
            print(f"       content[:80]: {item['content'][:80]!r}")


# ── 6. 链接发现 ────────────────────────────────────────────────────
async def demo_links():
    print(f"\n{SEP}")
    print("【6】discover_links — 提取页面链接")
    print(SEP)

    links = await discover_links(
        "https://httpbin.org/",
        same_domain=True,
        max_links=20,
    )

    print(f"发现 {len(links)} 条同域链接：")
    for link in links[:10]:
        print(f"  {link}")
    if len(links) > 10:
        print(f"  ... 共 {len(links)} 条")


# ── 7. 多类型网页：中英文 / PDF / 论文 / 博客 ──────────────────────────
async def demo_diverse():
    print(f"\n{SEP}")
    print("【7】多类型网页 — 中英文 · 论文 · PDF · 博客 · 百科")
    print(SEP)

    urls = [
        # ── 中文网页 ──
        ("https://baike.baidu.com/item/Python/407313", "百度百科 — Python"),
        ("https://www.ruanyifeng.com/blog/2024/01/weekly-issue-287.html", "阮一峰博客"),
        ("https://www.baidu.com/", "百度首页"),

        # ── 英文网页 ──
        ("https://www.bbc.com/news", "BBC News 首页"),
        ("https://news.ycombinator.com/", "HN 首页"),
        ("https://httpbin.org/html", "httpbin 测试页"),

        # ── 学术论文 ──
        ("https://arxiv.org/abs/1706.03762", "arXiv 摘要页 — Attention Is All You Need"),
        ("https://arxiv.org/abs/2304.10557", "arXiv 摘要页 — Segment Anything"),

        # ── PDF ──
        ("https://arxiv.org/pdf/1706.03762.pdf", "PDF — Attention 论文全文"),
        ("https://arxiv.org/pdf/2304.10557.pdf", "PDF — Segment Anything 论文"),

        # ── 文档 / API ──
        ("https://docs.python.org/3/", "Python 官方文档"),
        ("https://jsonplaceholder.typicode.com/posts/1", "JSON API 示例"),

        # ── GitHub ──
        ("https://github.com/torvalds/linux", "GitHub — Linux 仓库"),

        # ── 预期失败 ──
        ("https://this-does-not-exist-404.invalid/", "必定 404 / DNS 失败"),
    ]

    results = await read_many(
        [u for u, _ in urls],
        concurrency=5,
        strategy="fast",
    )

    name_map = {u: name for u, name in urls}
    for r in results:
        name = name_map.get(r.url, "?")
        status = "OK" if r.success else "FAIL"
        title = (r.title or "")[:50]
        print(f"  [{status}] {name}")
        print(f"         title={title!r}  status={r.status_code}  {r.elapsed_ms}ms")
        if r.error:
            print(f"         error={r.error}")

    succeeded = sum(1 for r in results if r.success)
    print(f"\n合计 {len(urls)} 个页面，成功 {succeeded}，失败 {len(urls) - succeeded}")


# ── 8. 错误处理演示 ────────────────────────────────────────────────
async def demo_error():
    print(f"\n{SEP}")
    print("【8】错误处理 — 结构化失败，不抛异常")
    print(SEP)

    result = await read_url("https://this-domain-does-not-exist-xyz.invalid/", strategy="fast")

    print(f"success      : {result.success}")
    print(f"error        : {result.error}")
    print(f"attempts     : {len(result.attempts)}")
    print(f"抛出异常了吗  : 没有，返回了结构化结果 OK")


# ── main ──────────────────────────────────────────────────────────
async def main():
    await demo_read_one()
    await demo_read_fast()
    await demo_read_many()
    await demo_agent()
    await demo_agent_many()
    await demo_links()
    await demo_diverse()
    await demo_error()

    print(f"\n{SEP}")
    print("全部示例运行完毕 OK")
    print(SEP)


if __name__ == "__main__":
    asyncio.run(main())
