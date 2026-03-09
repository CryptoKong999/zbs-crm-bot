from handlers.common import router as common_router
from handlers.schedule import router as schedule_router
from handlers.crm import router as crm_router
from handlers.finance import router as finance_router
from handlers.report import router as report_router

__all__ = [
    "common_router",
    "schedule_router",
    "crm_router",
    "finance_router",
    "report_router",
]
