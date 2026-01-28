import asyncio
from dotenv import load_dotenv
import os
from openai import AsyncOpenAI
from agents import OpenAIChatCompletionsModel
from typing import Literal
from openai import OpenAI


# 创建一个Deepseek模型
def createDeepseekModel(model: str):
    return OpenAIChatCompletionsModel(
        model=model,
        openai_client=AsyncOpenAI(
            base_url='https://api.deepseek.com/v1',
            api_key='YOUR DEEPSEEK API KEY'
        )
    )


# 创建一个Deepseek模型
def createGPTModel(model: str):
    return OpenAIChatCompletionsModel(
        model=model,
        openai_client=AsyncOpenAI(
            base_url='https://api.openai.com/v1',
            api_key='YOUR OPENAI API KEY'
        )
    )


def ds_chat_sync(model: str, messages: list):
    api_key = 'YOUR DEEPSEEK API KEY'
    client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

    response = client.chat.completions.create(
        model=model,
        messages=messages,
        stream=False
    )

    return response.choices[0].message.content


