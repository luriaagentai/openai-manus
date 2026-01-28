from agents import Agent, RunContextWrapper, RunHooks,Usage,Tool
import json
from typing import Any


# 通用的Agent状态响应类，会将当前Agent状态进行输出
class CommonHooks(RunHooks):
    def __init__(self, ws, main_agent: Agent=None, skip_agent: Agent=None):
        self.event_counter = 0
        self.ws = ws
        self.msg_id = ""
        self.main_agent = main_agent
        self.skip_agent = skip_agent
        self.current_agent = None

    def set_msgid(self, msg_id):
        self.msg_id = msg_id

    def set_main_agent(self, main_agent: Agent):
        self.main_agent = main_agent

    def set_skip_agent(self, skip_agent: Agent):
        self.skip_agent = skip_agent

    def get_skip_status(self):
        return self.skip_agent == self.current_agent

    def reset_counter(self):
        self.event_counter = 0

    def _usage_to_str(self, usage: Usage) -> str:
        return f"{usage.requests} requests, {usage.input_tokens} input tokens, {usage.output_tokens} output tokens, {usage.total_tokens} total tokens"

    async def on_agent_start(self, context: RunContextWrapper, agent: Agent) -> None:
        self.event_counter += 1
        print(
            f"### {self.event_counter}: 智能体 {agent.name} 开始运行。{agent == self.main_agent}"
        )
        self.current_agent = agent

        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "name": agent.name,
                "status": "start",
                "is_main": agent == self.main_agent,
                "msg_id": self.msg_id
            }))

    async def on_agent_end(self, context: RunContextWrapper, agent: Agent, output: Any) -> None:
        self.event_counter += 1
        print(
            f"\n### {self.event_counter}: 智能体 {agent.name} 运行结束。"
        )
        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "name": agent.name,
                "status": "end",
                "is_main": agent == self.main_agent,
                "msg_id": self.msg_id
            }))

    async def on_tool_start(self, context: RunContextWrapper, agent: Agent, tool: Tool) -> None:
        self.event_counter += 1
        print(
            f"### {self.event_counter}: 调用工具 {tool.name} 开始。"
        )
        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "name": agent.name,
                "status": "tool_start",
                "tool": tool.name,
                "msg_id": self.msg_id
            }))

    async def on_tool_end(
        self, context: RunContextWrapper, agent: Agent, tool: Tool, result: str
    ) -> None:
        self.event_counter += 1
        '''print(
            f"### {self.event_counter}: 调用工具 {tool.name} 结束。"
        )
        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "name": agent.name,
                "status": "tool_end",
                "tool": tool.name,
                "result": result,
                "msg_id": self.msg_id
            }))'''

    async def on_handoff(
        self, context: RunContextWrapper, from_agent: Agent, to_agent: Agent
    ) -> None:
        self.event_counter += 1
        print(
            f"\n### {self.event_counter}: 智能体 {from_agent.name} 交接任务到 {to_agent.name}。"
        )
        if self.ws is not None:
            await self.ws.send_text(json.dumps({
                "name": from_agent.name,
                "status": "end",
                "msg_id": self.msg_id
            }))

            await self.ws.send_text(json.dumps({
                "name": to_agent.name,
                "status": "handoff",
                "msg_id": self.msg_id
            }))
