import asyncio
import json
import os
from typing import Any, Dict, List, Optional
import aiofiles

DB_FILE = os.path.join(os.path.dirname(__file__), "database.json")

DEFAULT_DB: Dict[str, Any] = {
    "guilds": {},
    "tickets": {},
    "applications": {},
}


def _default_guild_settings(guild_id: int) -> Dict[str, Any]:
    return {
        "guild_id": guild_id,
        "log_channel": None,
        "welcome_channel": None,
        "welcome_message": "🕊️ Bem-vindo ao mosteiro, {usuario}! Que sua jornada em **{servidor}** seja de paz e propósito. ({membros} membros)",
        "farewell_channel": None,
        "farewell_message": "🕯️ {usuario} partiu do mosteiro.",
        "autorole": None,
        "verify_role": None,
        "reaction_roles": [],
        "role_panels": {},
        "scheduled_messages": [],
        "ticket_config": {
            "log_channel": None,
            "counter": 0,
            "categories": {
                "abade": {"category_id": None, "role_ids": []},
                "denuncia": {"category_id": None, "role_ids": []},
                "peticao": {"category_id": None, "role_ids": []},
                "privado": {"category_id": None, "role_ids": []},
            },
        },
        "app_config": {
            "review_channel": None,
            "mosteiro_role_id": None,
            "clero_role_id": None,
        },
    }


class JsonDatabase:
    """Persistência assíncrona em JSON com lock para evitar corrupção concorrente."""

    def __init__(self):
        self.lock = asyncio.Lock()
        if not os.path.exists(DB_FILE):
            with open(DB_FILE, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_DB, f, indent=4, ensure_ascii=False)

    async def _read(self) -> Dict[str, Any]:
        async with aiofiles.open(DB_FILE, mode="r", encoding="utf-8") as f:
            content = await f.read()
            if not content.strip():
                return json.loads(json.dumps(DEFAULT_DB))
            data = json.loads(content)
            for key, default_val in DEFAULT_DB.items():
                if key not in data:
                    data[key] = json.loads(json.dumps(default_val))
            return data

    async def _write(self, data: Dict[str, Any]):
        async with self.lock:
            async with aiofiles.open(DB_FILE, mode="w", encoding="utf-8") as f:
                await f.write(json.dumps(data, indent=4, ensure_ascii=False))

    async def get_guild_settings(self, guild_id: int) -> Dict[str, Any]:
        data = await self._read()
        guild_str = str(guild_id)
        defaults = _default_guild_settings(guild_id)

        if guild_str not in data["guilds"]:
            data["guilds"][guild_str] = defaults
            await self._write(data)
            return defaults

        changed = False
        current = data["guilds"][guild_str]
        for key, val in defaults.items():
            if key not in current:
                current[key] = val
                changed = True
        if changed:
            await self._write(data)
        return current

    async def update_guild(self, guild_id: int, key: str, value: Any):
        await self.get_guild_settings(guild_id)
        data = await self._read()
        data["guilds"][str(guild_id)][key] = value
        await self._write(data)

    async def unset_guild(self, guild_id: int, key: str):
        data = await self._read()
        guild_str = str(guild_id)
        if guild_str in data["guilds"] and key in data["guilds"][guild_str]:
            data["guilds"][guild_str][key] = None
            await self._write(data)

    async def add_to_set_guild(self, guild_id: int, key: str, value: Any) -> bool:
        settings = await self.get_guild_settings(guild_id)
        current = settings.get(key, [])
        if value not in current:
            current.append(value)
            await self.update_guild(guild_id, key, current)
            return True
        return False

    async def remove_from_set_guild(self, guild_id: int, key: str, value: Any) -> bool:
        settings = await self.get_guild_settings(guild_id)
        current = settings.get(key, [])
        if value in current:
            current.remove(value)
            await self.update_guild(guild_id, key, current)
            return True
        return False

    # --- TICKETS ---
    async def next_ticket_number(self, guild_id: int) -> int:
        settings = await self.get_guild_settings(guild_id)
        ticket_cfg = settings["ticket_config"]
        ticket_cfg["counter"] = int(ticket_cfg.get("counter", 0)) + 1
        await self.update_guild(guild_id, "ticket_config", ticket_cfg)
        return ticket_cfg["counter"]

    async def save_ticket(self, channel_id: int, ticket_doc: Dict[str, Any]):
        data = await self._read()
        data["tickets"][str(channel_id)] = ticket_doc
        await self._write(data)

    async def get_ticket(self, channel_id: int) -> Optional[Dict[str, Any]]:
        data = await self._read()
        return data["tickets"].get(str(channel_id))

    async def delete_ticket(self, channel_id: int):
        data = await self._read()
        if str(channel_id) in data["tickets"]:
            del data["tickets"][str(channel_id)]
            await self._write(data)

    async def list_open_tickets(self, guild_id: int, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        data = await self._read()
        results = []
        for t in data["tickets"].values():
            if t.get("guild_id") == guild_id and (user_id is None or t.get("author_id") == user_id):
                results.append(t)
        return results

    # --- APPLICATIONS (NOVICIADO / CLERO) ---
    async def save_application(self, app_id: str, app_doc: Dict[str, Any]):
        data = await self._read()
        data["applications"][app_id] = app_doc
        await self._write(data)

    async def get_application(self, app_id: str) -> Optional[Dict[str, Any]]:
        data = await self._read()
        return data["applications"].get(app_id)


db = JsonDatabase()
