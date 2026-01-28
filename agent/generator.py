

# 生成各种智能体的Agent，负责生成提示词、编写代码、挑选知识库
class GeneratorAgent:
    def __init__(self, ws):
        # 负责发送消息给前端
        self.ws = ws
        self.name = "Generator Agent"

    # 生成智能体，并发送消息
    def generate(self, name: str, instruction: str, msg_id: str):
        if self.ws is not None:
            # 生成开始
            self.ws.send_text(
                {
                    "name": self.name,
                    "status": "start",
                    "msg_id": msg_id
                }
            )

            # 开始生成
