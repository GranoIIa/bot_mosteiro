import discord
from discord import app_commands
from discord.ext import commands
from database.connection import db
from utils.permissions import AdminGroup


class Config(commands.Cog):
    """Configurações administrativas centrais do Mosteiro."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    config_group = AdminGroup(
        name="config",
        description="Configurações administrativas do Mosteiro",
    )

    @config_group.command(name="logchannel", description="Define o canal padrão de auditoria e logs.")
    @app_commands.describe(canal="Canal de texto onde os logs serão enviados")
    async def logchannel(self, interaction: discord.Interaction, canal: discord.TextChannel):
        await db.update_guild(interaction.guild_id, "log_channel", canal.id)
        await interaction.response.send_message(f"✅ Canal de logs definido para {canal.mention}.", ephemeral=True)

    @config_group.command(name="cargo_verificado", description="Define o cargo concedido ao concluir a verificação.")
    @app_commands.describe(cargo="Cargo de membro verificado")
    async def cargo_verificado(self, interaction: discord.Interaction, cargo: discord.Role):
        await db.update_guild(interaction.guild_id, "verify_role", cargo.id)
        await interaction.response.send_message(f"✅ Cargo de verificação definido para {cargo.mention}.", ephemeral=True)

    @config_group.command(name="reaction_role_add", description="Vincula uma reação em uma mensagem a um cargo.")
    @app_commands.describe(mensagem_id="ID da mensagem", emoji="Emoji da reação", cargo="Cargo a entregar")
    async def reaction_role_add(self, interaction: discord.Interaction, mensagem_id: str, emoji: str, cargo: discord.Role):
        if not mensagem_id.isdigit():
            await interaction.response.send_message("❌ O ID da mensagem deve conter apenas números.", ephemeral=True)
            return
        rr_obj = {"message_id": int(mensagem_id), "emoji": emoji.strip(), "role_id": cargo.id}
        await db.add_to_set_guild(interaction.guild_id, "reaction_roles", rr_obj)
        await interaction.response.send_message(
            f"🔗 Reaction Role configurada: {emoji} na mensagem `{mensagem_id}` → {cargo.mention}.",
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Config(bot))
