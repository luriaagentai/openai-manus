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
    handoff
)
from agents.extensions import handoff_filters
from llm.online import createDeepseekModel
from prompts.template import get_prompt_template
import asyncio, json
from tools.crawler import Crawler
from openai.types.responses import ResponseTextDeltaEvent
from pydantic import BaseModel
from agent.hooks import CommonHooks
from utils.json_utils import repair_json_output

set_tracing_disabled(True)

# 默认使用 DeepSeek-V3，2025-04-01
ds = createDeepseekModel("deepseek-chat")




