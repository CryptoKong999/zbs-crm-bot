from handlers.common import router as common_router
from handlers.common import fallback_router
from handlers.schedule import router as schedule_router
from handlers.crm import router as crm_router
from handlers.finance import router as finance_router
from handlers.report import router as report_router
from handlers.bloggers import router as bloggers_router

__all__ = [
    "common_router",
    "fallback_router",
    "schedule_router",
    "crm_router",
    "finance_router",
    "report_router",
    "bloggers_router",
]
