import discord
from discord import app_commands
from discord.ext import commands

# IDs com acesso total irrestrito em qualquer servidor, mesmo sem cargo de Administrador
OWNER_IDS = {309892822369304576}


async def check_admin_or_owner(interaction: discord.Interaction) -> bool:
    """Permite acesso ao dono do bot ou a administradores do servidor."""
    if interaction.user.id in OWNER_IDS:
        return True
    if interaction.guild and interaction.user.guild_permissions.administrator:
        return True
    raise app_commands.MissingPermissions(["administrator"])


def is_admin_or_owner():
    """Decorator para Slash Commands individuais."""
    return app_commands.check(check_admin_or_owner)


def is_ctx_admin_or_owner():
    """Decorator para comandos com prefixo (!) permitindo dono ou moderador/admin."""
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.author.id in OWNER_IDS:
            return True
        if ctx.guild and (
            ctx.author.guild_permissions.administrator
            or ctx.author.guild_permissions.manage_messages
        ):
            return True
        raise commands.MissingPermissions(["manage_messages"])

    return commands.check(predicate)


class AdminGroup(app_commands.Group):
    """Grupo de Slash Commands restrito a administradores do servidor ou donos do bot."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await check_admin_or_owner(interaction)
