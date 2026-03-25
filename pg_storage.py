"""
PostgreSQL-based FSM storage for aiogram 3.
Survives bot restarts — users don't lose in-progress forms.
"""

import json
import logging
from typing import Any, Dict, Optional

from aiogram.fsm.storage.base import BaseStorage, StorageKey
from aiogram.fsm.state import State
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy import text

logger = logging.getLogger(__name__)

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS fsm_storage (
    key TEXT PRIMARY KEY,
    state TEXT,
    data JSONB DEFAULT '{}'::jsonb,
    updated_at TIMESTAMP DEFAULT NOW()
)
"""


class PostgreSQLStorage(BaseStorage):
    """Minimal PostgreSQL storage for aiogram FSM."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self._session = session_factory

    async def init(self):
        """Create table if not exists."""
        async with self._session() as session:
            await session.execute(text(CREATE_TABLE))
            await session.commit()
        logger.info("FSM storage table ready")

    @staticmethod
    def _key(key: StorageKey) -> str:
        return f"{key.bot_id}:{key.chat_id}:{key.user_id}"

    async def set_state(self, key: StorageKey, state: Optional[str] = None) -> None:
        k = self._key(key)
        async with self._session() as session:
            await session.execute(
                text("""
                    INSERT INTO fsm_storage (key, state, updated_at)
                    VALUES (:k, :state, NOW())
                    ON CONFLICT (key) DO UPDATE SET state = :state, updated_at = NOW()
                """),
                {"k": k, "state": state},
            )
            await session.commit()

    async def get_state(self, key: StorageKey) -> Optional[str]:
        k = self._key(key)
        async with self._session() as session:
            result = await session.execute(
                text("SELECT state FROM fsm_storage WHERE key = :k"),
                {"k": k},
            )
            row = result.first()
            return row[0] if row else None

    async def set_data(self, key: StorageKey, data: Dict[str, Any]) -> None:
        k = self._key(key)
        async with self._session() as session:
            await session.execute(
                text("""
                    INSERT INTO fsm_storage (key, data, updated_at)
                    VALUES (:k, :data::jsonb, NOW())
                    ON CONFLICT (key) DO UPDATE SET data = :data::jsonb, updated_at = NOW()
                """),
                {"k": k, "data": json.dumps(data, ensure_ascii=False, default=str)},
            )
            await session.commit()

    async def get_data(self, key: StorageKey) -> Dict[str, Any]:
        k = self._key(key)
        async with self._session() as session:
            result = await session.execute(
                text("SELECT data FROM fsm_storage WHERE key = :k"),
                {"k": k},
            )
            row = result.first()
            return row[0] if row else {}

    async def close(self) -> None:
        pass
