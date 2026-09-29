"""SQLAlchemy models.

Importing this package registers every mapper on `Base.metadata`.
"""

from app.database.models.agent import Agent, AgentTool
from app.database.models.attachment import Attachment
from app.database.models.audit import AuditLog
from app.database.models.chunk import DocumentChunk
from app.database.models.conversation import Conversation, Message
from app.database.models.document import Document, DocumentStatus
from app.database.models.notification import Notification
from app.database.models.session import UserSession
from app.database.models.task import Task, TaskStatus
from app.database.models.tool import Tool
from app.database.models.user import User, UserSettings

__all__ = [
    "Agent",
    "Attachment",
    "AgentTool",
    "AuditLog",
    "Conversation",
    "Document",
    "DocumentChunk",
    "DocumentStatus",
    "Message",
    "Notification",
    "Task",
    "TaskStatus",
    "Tool",
    "User",
    "UserSession",
    "UserSettings",
]
