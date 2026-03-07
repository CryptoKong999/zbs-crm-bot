from handlers.common import router as common_router
from handlers.content import router as content_router
from handlers.crm import router as crm_router
from handlers.tasks import router as tasks_router
from handlers.finance import router as finance_router
from handlers.report import router as report_router

__all__ = [
    "common_router",
    "content_router", 
    "crm_router",
    "tasks_router",
    "finance_router",
    "report_router",
]
