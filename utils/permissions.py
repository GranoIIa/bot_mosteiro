import discord
from discord import app_commands

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


class AdminGroup(app_commands.Group):
    """Grupo de Slash Commands restrito a administradores do servidor ou donos do bot."""

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return await check_admin_or_owner(interaction)
