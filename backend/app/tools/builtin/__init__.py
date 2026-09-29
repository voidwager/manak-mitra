"""Built-in tool implementations.

Each module holds one tool (or a closely related pair). Nothing outside
`app.tools` imports these directly - the registry is the entry point, so
permission checks cannot be bypassed by reaching for an implementation.
"""

from app.tools.builtin.calculator import CalculatorTool
from app.tools.builtin.data_analysis import DataAnalysisTool
from app.tools.builtin.reporting import ReportGeneratorTool
from app.tools.builtin.retrieval import DocumentSearchTool, KnowledgeRetrievalTool

__all__ = [
    "CalculatorTool",
    "DataAnalysisTool",
    "DocumentSearchTool",
    "KnowledgeRetrievalTool",
    "ReportGeneratorTool",
]
