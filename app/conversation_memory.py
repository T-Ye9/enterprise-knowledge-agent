"""单进程短期会话；不存储客户端、API Key 或环境配置。"""

from uuid import uuid4

from langgraph.checkpoint.memory import InMemorySaver


class ConversationMemory:
    def __init__(self):
        self.checkpointer = InMemorySaver()
        self.session_ids: set[str] = set()

    def create(self) -> str:
        session_id = str(uuid4())
        self.session_ids.add(session_id)
        return session_id

    def exists(self, session_id: str) -> bool:
        return session_id in self.session_ids

    def delete(self, session_id: str):
        self.checkpointer.delete_thread(session_id)
        self.session_ids.remove(session_id)
