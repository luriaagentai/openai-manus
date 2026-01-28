import os.path
import uuid

from agents import (
    Agent,
    Runner,
    set_tracing_disabled,
    function_tool,
    TResponseInputItem,
    output_guardrail,
    GuardrailFunctionOutput,
    RunContextWrapper,
    OutputGuardrailTripwireTriggered,
    HandoffInputData,
    handoff,
    FunctionTool,
    RunConfig,
    ModelSettings
)
from agents.extensions import handoff_filters
from llm.online import createDeepseekModel, createGPTModel, ds_chat_sync
from prompts.template import get_prompt_template
import asyncio, json
from tools.crawler import Crawler
from openai.types.responses import ResponseTextDeltaEvent, ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
from pydantic import BaseModel
from agent.hooks import CommonHooks
from utils.json_utils import repair_json_output
from tools.coder import python_repl_tool, bash_tool
from typing import Any
import traceback
from agents.items import MessageOutputItem

set_tracing_disabled(True)

SERVER_URL = "http://192.168.1.5:7820/"

# 默认使用 DeepSeek-V3，2025-04-01
ds = createDeepseekModel("deepseek-chat")
gpt_model = createGPTModel("gpt-4o")


# 针对输出进行判断的智能体
guardrail_agent = Agent(
    name="Guardrail check",
    instructions='''
            Check if the user has confirmed or satisfied with the plan. 
            You must response in json format!!!
            
            EXAMPLE JSON OUTPUT:
            { 
                'is_confirmed': False
            } 
            ''',
    model=ds
)

# 最终的计划结构体
final_plan = {}


# 判定规划智能体是否完成任务
@output_guardrail
async def generator_guardrail(
    context: RunContextWrapper[None], agent: Agent, input: str | list[TResponseInputItem]
) -> GuardrailFunctionOutput:
    """This is an input guardrail function, which happens to call an agent to check if the input
    is a math homework question.
    """
    global final_plan
    # print(f"Guardrail result: {result.final_output}")

    decode_success = True

    try:
        final_plan = json.loads(repair_json_output(repair_json_output(input)))

    except Exception:
        print("Json decode fail")
        decode_success = True

    return GuardrailFunctionOutput(
        output_info=input,
        tripwire_triggered=decode_success,
    )


# 判定规划智能体是否完成任务
@output_guardrail
async def planner_guardrail(
    context: RunContextWrapper[None], agent: Agent, input: str | list[TResponseInputItem]
) -> GuardrailFunctionOutput:
    """This is an input guardrail function, which happens to call an agent to check if the input
    is a math homework question.
    """
    global final_plan
    # print(f"Guardrail result: {result.final_output}")

    decode_success = True

    try:
        final_plan = json.loads(repair_json_output(repair_json_output(input)))

    except Exception:
        print("Json decode fail")
        decode_success = True

    return GuardrailFunctionOutput(
        output_info=input,
        tripwire_triggered=decode_success,
    )


async def stream_text(stream_result):
    async for event in stream_result.stream_events():
        if event.type == "raw_response_event":
            if isinstance(event.data, ResponseTextDeltaEvent):
                print(event.data.delta, end="", flush=True)


class CrawlerToolArgs(BaseModel):
    url: str


# 网络爬虫工具，方便Master Agent查询openai agents相关的代码信息
@function_tool
def online_crawler(url: str) -> str:
    crawl = Crawler()
    article = crawl.crawl(url)
    return article


class SearchToolArgs(BaseModel):
    query: str


# 网络搜索工具，方便Master Agent查询openai agents相关的代码信息
@function_tool
def online_search(query: str) -> str:
    crawl = Crawler()
    return crawl.search(query)


class CodeToolArgs(BaseModel):
    input_code: str


# 代码执行工具，方便Agent直接执行python代码
@function_tool
def code_execution(input_code: str) -> str:
    return python_repl_tool(input_code)


# Agent入口
class MasterAgent:
    def __init__(self, ws):
        self.ws = ws

        self.input_data: list[TResponseInputItem] = []
        self.hooks = CommonHooks(ws)
        self.complete = False
        self.msgid = ""

        # 任务规划师
        self.planneragent = Agent(
            name="Planner Agent",
            instructions=get_prompt_template("planner_fixed", {}),
            model=ds,
            handoff_description="User input agent planning tool, help user to generate and change plans"
        )

        # 智能体生成师
        self.generatoragent = Agent(
            name="Generator Agent",
            instructions=get_prompt_template("generator", {}),
            model=ds,
            handoff_description="User input agent generating tool, can genrator agents by current plans.",
            output_guardrails=[generator_guardrail]
        )

        # 主Agent入口
        self.masteragent = Agent(
            name="Master Agent",
            instructions=get_prompt_template("master", {}),
            model=ds,
            handoffs=[self.planneragent, self.generatoragent]
        )

        self.SearchTool = FunctionTool(
            name="online_search",
            description="A search tool that can get online information by query",
            params_json_schema=SearchToolArgs.model_json_schema(),
            on_invoke_tool=self.online_search
        )

        self.CrawlerTool = FunctionTool(
            name="online_crawler",
            description="A tool that can grab certain information by url",
            params_json_schema=CrawlerToolArgs.model_json_schema(),
            on_invoke_tool=self.online_crawler
        )

        self.CodeTool = FunctionTool(
            name="code_execution",
            description="A tool that can excute python, and get result.",
            params_json_schema=CodeToolArgs.model_json_schema(),
            on_invoke_tool=self.code_execution
        )

        self.ShellTool = FunctionTool(
            name="shell_execution",
            description="A tool that can excute bash or cmd code, and get result.",
            params_json_schema=CodeToolArgs.model_json_schema(),
            on_invoke_tool=self.shell_execution
        )

    def handoff_message_filter(self, handoff_message_data: HandoffInputData) -> HandoffInputData:
        # First, we'll remove any tool-related messages from the message history
        handoff_message_data = handoff_filters.remove_all_tools(handoff_message_data)

        # self.input_data.append(handoff_message_data.new_items[0].raw_item)

        task_input = [{
            "role": "system",
            "content": get_prompt_template("supervisior_task", {})
        }]

        # 历史记录
        for his in handoff_message_data.input_history:
            if type(his["content"]) is str and "[ ]" in his["content"]:
                task_input.append({
                    "content": his["content"],
                    "role": his["role"]
                })
            elif type(his["content"]) is list and "[ ]" in his["content"][0]["text"]:
                # print(his["content"][0]["text"])
                task_input.append({
                    "content": his["content"][0]["text"],
                    "role": his["content"][0]["role"] if "role" in his["content"][0] else "assistant"
                })

        # 新生成的记录
        for new_item in handoff_message_data.new_items:
            if "[ ]" in new_item.raw_item.content[0].text:
                task_input.append({
                    "content": new_item.raw_item.content[0].text,
                    "role": "assistant"
                })

            # 将这部分加到历史对话中，因为后续不使用了
            self.input_data.append(new_item.to_input_item())

        # print(task_input)
        current_task = ds_chat_sync("deepseek-chat", task_input)
        print(current_task)

        if self.ws is not None:
            asyncio.create_task(self.ws.send_text(json.dumps({
                "status": "xtool",
                "text": current_task,
                "msg_id": self.msgid
            })))

        handoff_input = MessageOutputItem(agent=Any, raw_item=ResponseOutputMessage(id='__fake_id__',
                                                                                    content=[ResponseOutputText(
                                                                                        annotations=[],
                                                                                        text=f"{current_task}。",
                                                                                        type="output_text")],
                                                                                    role="assistant",
                                                                                    status="completed",
                                                                                    type="message"))

        # Second, we'll also remove the first two items from the history, if history is too long.
        history = handoff_message_data.input_history if isinstance(handoff_message_data.input_history, tuple) else ()

        # for his in history:
            # print(his)

        return HandoffInputData(
            input_history=(),
            pre_handoff_items=tuple(handoff_message_data.pre_handoff_items),
            new_items=tuple([handoff_input]),
        )

    def handoff_message_filter_coder(self, handoff_message_data: HandoffInputData) -> HandoffInputData:
        # First, we'll remove any tool-related messages from the message history
        handoff_message_data = handoff_filters.remove_all_tools(handoff_message_data)

        # self.input_data.append(handoff_message_data.new_items[0].raw_item)

        task_input = [{
            "role": "system",
            "content": get_prompt_template("supervisior_task", {})
        }]

        # 历史记录
        for his in handoff_message_data.input_history:
            if type(his["content"]) is str and "[ ]" in his["content"]:
                task_input.append({
                    "content": his["content"],
                    "role": his["role"]
                })
            elif type(his["content"]) is list and "[ ]" in his["content"][0]["text"] :
                # print(his["content"][0]["text"])
                task_input.append({
                    "content": his["content"][0]["text"],
                    "role": his["content"][0]["role"] if "role" in his["content"][0] else "assistant"
                })

        # 新生成的记录
        for new_item in handoff_message_data.new_items:
            if "[ ]" in new_item.raw_item.content[0].text:
                task_input.append({
                    "content": new_item.raw_item.content[0].text,
                    "role": "assistant"
                })

            # 将这部分加到历史对话中，因为后续不使用了
            self.input_data.append(new_item.to_input_item())

        # print(task_input)
        current_task = ds_chat_sync("deepseek-chat", task_input)
        print(current_task)

        if self.ws is not None:
            asyncio.create_task(self.ws.send_text(json.dumps({
                "status": "xtool",
                "text": current_task,
                "msg_id": self.msgid
            })))

        handoff_input = MessageOutputItem(agent=Any, raw_item=ResponseOutputMessage(id='__fake_id__',
                                                                                    content=[ResponseOutputText(
                                                                                        annotations=[],
                                                                                        text=f"{current_task}。",
                                                                                        type="output_text")],
                                                                                    role="assistant",
                                                                                    status="completed",
                                                                                    type="message"))

        # Second, we'll also remove the first two items from the history, if history is too long.
        history = []

        # 去掉历史记录中的任务清单，防止子智能体生成任务清单
        for his in handoff_message_data.input_history:
            if type(his["content"]) is str and "[ ]" not in his["content"]:
                history.append(his)
            elif type(his["content"]) is list and "[ ]" not in his["content"][0]["text"]:
                # print(his["content"][0]["text"])
                history.append(his)

        return HandoffInputData(
            input_history=tuple(history),
            pre_handoff_items=tuple(handoff_message_data.pre_handoff_items),
            new_items=tuple([handoff_input]),
        )

    def handoff_message_filter_reporter(self, handoff_message_data: HandoffInputData) -> HandoffInputData:
        # First, we'll remove any tool-related messages from the message history
        handoff_message_data = handoff_filters.remove_all_tools(handoff_message_data)

        # 去掉历史记录中的任务清单，防止子智能体生成任务清单
        history = []

        for his in handoff_message_data.input_history:
            if type(his["content"]) is str and "[ ]" not in his["content"]:
                history.append(his)
            elif type(his["content"]) is list and "[ ]" not in his["content"][0]["text"]:
                # print(his["content"][0]["text"])
                history.append(his)

        return HandoffInputData(
            input_history=tuple(history),
            pre_handoff_items=tuple(handoff_message_data.pre_handoff_items),
            new_items=handoff_message_data.new_items,
        )

    # 网络爬虫工具，方便Master Agent查询openai agents相关的代码信息
    async def online_crawler(self, ctx: RunContextWrapper[Any], url: str) -> str:

        real_url = json.loads(repair_json_output(url))["url"]

        print(f"开始爬取目标：{real_url}")

        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "status": "tool_target",
                "xtool": f"爬取链接：{real_url}",
                "msg_id": self.msgid
            }))

        crawl = Crawler()
        article = crawl.crawl(real_url)
        # Tool end
        print(
            f"### 调用工具 online_crawler 结束。"
        )

        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "status": "tool_end",
                "tool": "online_crawler",
                "result": article,
                "msg_id": self.msgid
            }))

        return article

    # 网络搜索工具，方便Master Agent查询openai agents相关的代码信息
    async def online_search(self, ctx: RunContextWrapper[Any], query: str) -> str:

        real_query = json.loads(repair_json_output(query))["query"]

        print(f"开始搜索{real_query}")

        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "status": "tool_target",
                "xtool": f"搜索{real_query}",
                "msg_id": self.msgid
            }))

        crawl = Crawler()
        result = crawl.search(real_query)

        # Tool end
        print(
            f"### 调用工具 online_search 结束。"
        )

        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "status": "tool_end",
                "tool": "online_search",
                "result": result,
                "msg_id": self.msgid
            }))

        return result

    # 代码执行工具，方便Agent直接执行python代码
    async def code_execution(self, ctx: RunContextWrapper[Any], input_code: str) -> str:

        real_input_code = json.loads(repair_json_output(input_code))["input_code"]

        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "status": "tool_target",
                "xtool": f"执行以下代码：{real_input_code}",
                "msg_id": self.msgid
            }))

        result = python_repl_tool(real_input_code)

        # Tool end
        print(
            f"### 调用工具 code_execution 结束。"
        )

        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "status": "tool_end",
                "tool": "code_execution",
                "result": result,
                "msg_id": self.msgid
            }))

        return result

    # 脚本执行工具，方便Agent直接执行cmd和shell代码
    async def shell_execution(self, ctx: RunContextWrapper[Any], input_code: str) -> str:

        real_input_code = json.loads(repair_json_output(input_code))["input_code"]

        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "status": "tool_target",
                "xtool": f"执行以下代码：{real_input_code}",
                "msg_id": self.msgid
            }))

        result = bash_tool(real_input_code)

        # Tool end
        print(
            f"### 调用工具 shell_execution 结束。"
        )

        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "status": "tool_end",
                "tool": "shell_execution",
                "result": result,
                "msg_id": self.msgid
            }))

        return result

    async def chat(self, user_input, msgid):
        self.hooks.reset_counter()
        self.hooks.set_msgid(msgid)
        self.msgid = msgid
        self.input_data.append(
            {
                "role": "user",
                "content": user_input,
            }
        )

        try:
            self.hooks.set_main_agent(self.masteragent)

            result = Runner.run_streamed(self.masteragent, self.input_data, hooks=self.hooks)

            async for event in result.stream_events():
                if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                    print(event.data.delta, end="", flush=True)
                    if self.ws is not None:
                        await self.ws.send_text(json.dumps({
                            "text": event.data.delta,
                            "msg_id": self.msgid
                        }))

            self.input_data = result.to_input_list()

        except OutputGuardrailTripwireTriggered as e:
            # 完成生成
            if self.ws is not None:
                await self.ws.send_text(json.dumps({
                    "name": "Generator agent",
                    "status": "ready",
                    "msg_id": self.msgid
                }))

            '''
            try:
                # 说明已经完成json的生成，那么开始执行智能体生成
                # TODO: 现根据规划结果，进行智能体生成
                for member in final_plan["team"]:
                    if not member["is_generated"]:
                        print(f"开始生成智能体{member['name']}...")

                        if self.ws is not None:
                            await self.ws.send_text(json.dumps({
                                "name": "Generator agent",
                                "status": "generate start",
                                "target": member["name_cn"],
                                "msg_id": self.msgid
                            }))

                        # 开始生成代码
                        if self.ws is not None:
                            await self.ws.send_text(json.dumps({
                                "name": "Generator agent",
                                "status": "step start",
                                "target": "code",
                                "msg_id": self.msgid
                            }))

                        singleagent04 = Agent(
                            name="Single Agent",
                            instructions=get_prompt_template("generator_code", {
                                "NAME": member["name_cn"],
                                "INSTRUCTION": member["instruction"]
                            }),
                            model=ds
                        )

                        result = Runner.run_streamed(singleagent04, "请生成对应的智能体的python代码")

                        async for event in result.stream_events():
                            if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                                print(event.data.delta, end="", flush=True)
                                if self.ws is not None:
                                    await self.ws.send_text(json.dumps({
                                        "text": event.data.delta,
                                        "msg_id": self.msgid
                                    }))

                        # 结束生成代码
                        if self.ws is not None:
                            await self.ws.send_text(json.dumps({
                                "name": "Generator agent",
                                "status": "step end",
                                "target": "code",
                                "msg_id": self.msgid
                            }))

                        print(f"智能体{member['name']}生成结束...")

                        # 生成结束
                        if self.ws is not None:
                            await self.ws.send_text(json.dumps({
                                "name": "Generator agent",
                                "status": "generate end",
                                "target": member["name"],
                                "msg_id": self.msgid
                            }))

                # 完成生成
                if self.ws is not None:
                    await self.ws.send_text(json.dumps({
                        "name": "Generator agent",
                        "status": "ready",
                        "msg_id": self.msgid
                    }))
            except Exception:
                # 任务执行结束
                if self.ws is not None:
                    await self.ws.send_text(json.dumps({
                        "status": "task end",
                        "msg_id": self.msgid
                    }))
            '''





    # 最终任务执行
    async def executing(self, input_task, msgid):

        '''
        # 首先根据输入任务分解为步骤
        excutor_agent = Agent(
            name="excutor agent",
            instructions=get_prompt_template("executor", {}),
            model=ds
        )

        try:

            plan_result = Runner.run_streamed(excutor_agent, input_task, hooks=self.hooks)

            async for event in plan_result.stream_events():
                if event.type == "raw_response_event" and isinstance(event.data, ResponseTextDeltaEvent):
                    print(event.data.delta, end="", flush=True)
                    if self.ws is not None:
                        await self.ws.send_text(json.dumps({
                            "text": event.data.delta,
                            "msg_id": self.msgid
                        }))

        except Exception as e:
            print(f"Error: {e}")

             # 任务执行结束
            if self.ws is not None:
                await self.ws.send_text(json.dumps({
                    "status": "task end",
                    "msg_id": self.msgid
            }))

            return

        plan = json.loads(repair_json_output(repair_json_output(plan_result.final_output)))

        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "agent": json.dumps(plan),
                "msg_id": self.msgid
            }))

        # TODO: 生成结束后，将规划的任务结果扔给监理智能体，开始任务执行
        team_members = []
        member_tip = ""
        for member in plan["team"]:
            team_members.append(member["name"])
            member_tip += f"-**{member['name']}**: {member['instruction']}\n"
        state_list = {
            "TEAM_MEMBERS": team_members,
            "MEMBER_TOOLTIP": member_tip
        }
        '''

        reporter = Agent(
            name="reporter_agent",
            instructions=get_prompt_template("reporter", {}),
            model=ds,
            handoff_description="An agent can write a final report."
        )

        searcher = Agent(
            name="searcher_agent",
            instructions=get_prompt_template("research", {}),
            model=gpt_model,
            tools=[self.SearchTool, self.CrawlerTool],
            handoff_description="An agent can search online infomations and grab directly from web url.",
        )

        coder = Agent(
            name="coder_agent",
            instructions=get_prompt_template("coder", {
                "FILE_SAVE": "F:\\\\DeepLearning\\\\AgentServer\\\\tools\\\\workspace",
                "SERVER_URL": SERVER_URL
            }),
            model=ds,
            tools=[self.CodeTool, self.ShellTool],
            handoff_description="An agent can write python and shell code for task, and execute with tool."
        )

        planner = Agent(
            name="Supervisior Agent",
            instructions=get_prompt_template("planner", {}),
            model=ds
        )

        supervisior = Agent(
            name="Coordinate Agent",
            instructions=get_prompt_template("supervisior", {}),
            model=ds,
            handoffs=[# handoff(browser, input_filter=self.handoff_message_filter),
                      # handoff(reporter, input_filter=self.handoff_message_filter_coder),
                      handoff(searcher, input_filter=self.handoff_message_filter),
                      handoff(coder, input_filter=self.handoff_message_filter_coder)],
        )

        self.hooks.reset_counter()
        self.hooks.set_msgid(msgid)
        self.msgid = msgid

        self.input_data = []
        '''
        self.input_data.append(
            {
                "role": "user",
                "content": "当前计划如下: \n" + json.dumps(plan),
            }
        )
        '''

        self.input_data.append(
            {
                "role": "user",
                "content": input_task,
                "type": "message"
            }
        )

        while True:
            try:
                # 需要过滤掉工具输出，防止监管Agent尝试去调用不存在的工具
                input_data = []
                for input_data_s in self.input_data:
                    # print(input_data_s)
                    if input_data_s["type"] == "message":
                        input_data.append(input_data_s)
                        # print(input_data_s)

                self.hooks.set_main_agent(planner)

                run_config = RunConfig(
                    model_settings=ModelSettings(
                        tool_choice='required',
                        parallel_tool_calls=False
                    )
                )
                plan = Runner.run_streamed(planner, input_data, hooks=self.hooks, run_config=run_config)

                async for event in plan.stream_events():
                    if event.type == "raw_response_event":
                        if isinstance(event.data, ResponseTextDeltaEvent):
                            print(event.data.delta, end="", flush=True)
                            if self.ws is not None:
                                await self.ws.send_text(json.dumps({
                                    "text": event.data.delta,
                                    "msg_id": self.msgid
                                }))

                if len(plan.final_output) <= 5:
                    continue

                # 将新结果全部放入历史对话
                for item in plan.new_items:
                    self.input_data.append(item.to_input_item())
                    if item.to_input_item()["type"] == "message":
                        input_data.append(item.to_input_item())

                self.hooks.set_main_agent(supervisior)
                self.hooks.set_skip_agent(supervisior)

                result = Runner.run_streamed(supervisior, input_data, hooks=self.hooks, max_turns=50)

                async for event in result.stream_events():
                    if event.type == "raw_response_event":
                        if isinstance(event.data, ResponseTextDeltaEvent):
                            print(event.data.delta, end="", flush=True)
                            if self.ws is not None and (not self.hooks.get_skip_status()):
                                await self.ws.send_text(json.dumps({
                                    "text": event.data.delta,
                                    "msg_id": self.msgid
                                }))

                # 将新结果全部放入历史对话
                for item in result.new_items:
                    self.input_data.append(item.to_input_item())

            except Exception as e:
                print(f"Error: {e}. type: {type(e)}.")
                print('\n', '>>>' * 20)
                print(traceback.print_exc())

                # 任务执行结束
                if self.ws is not None:
                    await self.ws.send_text(json.dumps({
                        "status": "task end",
                        "msg_id": self.msgid
                    }))

                break

            if ("next" in result.final_output) and ("FINISH" in result.final_output):
                print("任务执行结束")


async def main():
    testma = MasterAgent(None)

    mode = ""

    while not testma.complete:
        if type(mode) != bool:
            # 设置输入模式
            mode = input("请输入运行模式：\n1 - 智能体生成模式\n2 - 智能体执行模式\n: ")

            if mode == "1":
                mode = False
            elif mode == "2":
                mode = True
            else:
                continue

        input_msg = input("请输入信息： ")
        if mode:
            await testma.executing(input_msg, str(uuid.uuid4()))
        else:
            await testma.chat(input_msg, str(uuid.uuid4()))


if __name__ == "__main__":
    asyncio.run(main())
