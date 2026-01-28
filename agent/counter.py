# 专门用来计数的类
class MessageCounter:
    def __init__(self):
        self.counter = 0

    def reset(self):
        self.counter = 0

    # 新增计数
    def increase(self, delta: int):
        self.counter += delta

    # 获取当前计数
    def getcounter(self):
        return self.counter
