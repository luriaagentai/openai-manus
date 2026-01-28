import logging
import sys
from urllib.parse import  quote
import requests

logger = logging.getLogger(__name__)

JINA_API_KEY = "YOUR JINA API KEY"


class JinaClient:
    def crawl(self, url: str, return_format: str = "html") -> str:
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {JINA_API_KEY}",
            "X-Return-Format": return_format
        }

        data = {"url": url}
        response = requests.post("https://r.jina.ai/", headers=headers, json=data)
        return response.text

    def search(self, query: str) -> str:
        headers = {
            "X-Respond-With": "no-content",
            "Authorization": f"Bearer {JINA_API_KEY}"
        }

        response = requests.post(url=f"https://s.jina.ai/?q={quote(query)}&hl=zh-cn&gl=CN", headers=headers)
        response.encoding = response.apparent_encoding
        return response.text


class Crawler:
    def crawl(self, url: str) -> str:
        # To help LLMs better understand content, we extract clean
        # articles from HTML, convert them to markdown, and split
        # them into text and image blocks for one single and unified
        # LLM message.
        #
        # Jina is not the best crawler on readability, however it's
        # much easier and free to use.
        #
        # Instead of using Jina's own markdown converter, we'll use
        # our own solution to get better readability results.
        jina_client = JinaClient()
        article = jina_client.crawl(url, return_format="markdown")
        if len(article) > 4000:
            article = article[:4000]
        return article

    def search(self, query: str) -> str:
        jina_client = JinaClient()
        res = jina_client.search(query).encode('utf-8')
        return res.decode('utf-8')


if __name__ == "__main__":
    if len(sys.argv) == 2:
        url = sys.argv[1]
    else:
        url = "https://finance.sina.com.cn/wm/2024-11-16/doc-incwfiet9354394.shtml"
    crawler = Crawler()
    article = crawler.crawl(url)
    print(article)
