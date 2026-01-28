from agents import Agent, OpenAIChatCompletionsModel, function_tool, set_tracing_disabled, handoff, HandoffInputData, RunContextWrapper, Runner
from openai import AsyncOpenAI
from openai.types.responses import ResponseTextDeltaEvent
import asyncio
from tools.crawler import Crawler
from tools.browser import BrowserTool
from agent.hooks import CommonHooks
from agent.counter import MessageCounter

set_tracing_disabled(True)

# 网络爬虫工具，方便Master Agent查询openai agents相关的代码信息
@function_tool
def online_crawler(url: str) -> str:
    crawl = Crawler()
    article = crawl.crawl(url)
    return article.to_markdown()


# 网络搜索工具，方便Master Agent查询openai agents相关的代码信息
@function_tool
def online_search(query: str) -> str:
    crawl = Crawler()
    return crawl.search(query)


# 浏览器调用工具
@function_tool
async def browser_use_tool(input_task: str) -> str:
    browser_agent = BrowserTool(input_task)
    result = await browser_agent.run()
    return result


# 创建一个Deepseek模型
def createDeepseekModel(model: str):
    return OpenAIChatCompletionsModel(
        model=model,
        openai_client=AsyncOpenAI(
            base_url='https://api.deepseek.com/v1',
            api_key='sk-bc6f72c399f0465db95278a854a0749b',  # 'sk-47c0b8503a974e41ac1b689cd8e8d3fc'
        )
    )


async def main():
    ds = createDeepseekModel("deepseek-chat")
    assistant = Agent(
        name="Research assistant agent",
        instructions="Use your tool to get paper information for user. You must answer user with known information. You must not make fake informations.",
        model=ds,
        tools=[online_search, online_crawler, browser_use_tool]
    )

    input_data = []

    counter = MessageCounter()
    hook = CommonHooks(None, counter)

    while True:
        task = input("请输入问题：")

        input_data.append(
            {
                "role": "user",
                "content": task,
            }
        )

        result = Runner.run_streamed(assistant, input_data, hooks=hook)

        async for event in result.stream_events():
            if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                print(event.data.delta, end="", flush=True)

        input_data = result.to_input_list()

if __name__ == "__main__":
    asyncio.run(main())
