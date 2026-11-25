import datetime
import discord
from discord.ext import commands
from database.connection import db


class Logs(commands.Cog):
    """Auditoria passiva de eventos do servidor."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def get_log_channel(self, guild: discord.Guild):
        settings = await db.get_guild_settings(guild.id)
        channel_id = settings.get("log_channel")
        return guild.get_channel(channel_id) if channel_id else None

    @commands.Cog.listener()
    async def on_message_delete(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        log_channel = await self.get_log_channel(message.guild)
        if not log_channel:
            return
        embed = discord.Embed(
            title="🗑️ Mensagem Deletada",
            description=(
                f"**Autor:** {message.author.mention}\n"
                f"**Canal:** {message.channel.mention}\n"
                f"**Conteúdo:**\n{message.content or '[Sem texto / Apenas mídia]'}"
            ),
            color=discord.Color.red(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        await log_channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        if before.author.bot or not before.guild or before.content == after.content:
            return
        log_channel = await self.get_log_channel(before.guild)
        if not log_channel:
            return
        embed = discord.Embed(
            title="✏️ Mensagem Editada",
            description=(
                f"**Autor:** {before.author.mention}\n"
                f"**Canal:** {before.channel.mention}\n"
                f"[Ir para mensagem]({after.jump_url})"
            ),
            color=discord.Color.gold(),
            timestamp=datetime.datetime.now(datetime.timezone.utc),
        )
        embed.add_field(name="Antes", value=(before.content or "Vazio")[:1024], inline=False)
        embed.add_field(name="Depois", value=(after.content or "Vazio")[:1024], inline=False)
        await log_channel.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Logs(bot))
