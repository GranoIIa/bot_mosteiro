import time
import uuid
import discord
from discord import app_commands
from discord.ext import commands, tasks
from database.connection import db
from utils.permissions import AdminGroup, is_ctx_admin_or_owner


class Chancelaria(commands.Cog):
    """Mensagens automáticas (boas-vindas, despedidas e avisos agendados)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def cog_unload(self):
        if self.scheduled_loop.is_running():
            self.scheduled_loop.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        if not self.scheduled_loop.is_running():
            self.scheduled_loop.start()

    chancelaria_group = AdminGroup(
        name="chancelaria",
        description="Mensagens automáticas e avisos periódicos do Mosteiro",
    )

    @chancelaria_group.command(name="boas_vindas", description="Configura o canal e a mensagem de boas-vindas.")
    @app_commands.describe(
        canal="Canal de boas-vindas (deixe vazio para desativar)",
        mensagem="Use {usuario}, {servidor} e {membros}",
    )
    async def boas_vindas(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel = None,
        mensagem: str = None,
    ):
        if canal is None:
            await db.unset_guild(interaction.guild_id, "welcome_channel")
            await interaction.response.send_message("🔴 Boas-vindas automáticas desativadas.", ephemeral=True)
            return

        await db.update_guild(interaction.guild_id, "welcome_channel", canal.id)
        if mensagem:
            await db.update_guild(interaction.guild_id, "welcome_message", mensagem)
        await interaction.response.send_message(
            f"✅ Boas-vindas configuradas em {canal.mention}.",
            ephemeral=True,
        )

    @chancelaria_group.command(name="despedida", description="Configura o canal e a mensagem de saída.")
    @app_commands.describe(
        canal="Canal de despedida (deixe vazio para desativar)",
        mensagem="Use {usuario} e {servidor}",
    )
    async def despedida(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel = None,
        mensagem: str = None,
    ):
        if canal is None:
            await db.unset_guild(interaction.guild_id, "farewell_channel")
            await interaction.response.send_message("🔴 Mensagem de despedida desativada.", ephemeral=True)
            return

        await db.update_guild(interaction.guild_id, "farewell_channel", canal.id)
        if mensagem:
            await db.update_guild(interaction.guild_id, "farewell_message", mensagem)
        await interaction.response.send_message(
            f"✅ Despedida configurada em {canal.mention}.",
            ephemeral=True,
        )

    @chancelaria_group.command(name="agendar", description="Cria uma mensagem automática recorrente.")
    @app_commands.describe(
        canal="Canal onde a mensagem será enviada",
        intervalo_minutos="Intervalo em minutos (mínimo 5)",
        mensagem="Texto da mensagem automática",
    )
    async def agendar(
        self,
        interaction: discord.Interaction,
        canal: discord.TextChannel,
        intervalo_minutos: app_commands.Range[int, 5, 10080],
        mensagem: str,
    ):
        settings = await db.get_guild_settings(interaction.guild_id)
        schedules = settings.get("scheduled_messages", [])
        job_id = str(uuid.uuid4())[:8]
        schedules.append(
            {
                "id": job_id,
                "channel_id": canal.id,
                "interval_minutes": intervalo_minutos,
                "message": mensagem,
                "last_run": time.time(),
            }
        )
        await db.update_guild(interaction.guild_id, "scheduled_messages", schedules)
        await interaction.response.send_message(
            f"🕰️ Aviso agendado (`{job_id}`) em {canal.mention} a cada **{intervalo_minutos} min**.",
            ephemeral=True,
        )

    @chancelaria_group.command(name="listar_agendamentos", description="Lista todas as mensagens automáticas agendadas.")
    async def listar_agendamentos(self, interaction: discord.Interaction):
        settings = await db.get_guild_settings(interaction.guild_id)
        schedules = settings.get("scheduled_messages", [])
        if not schedules:
            await interaction.response.send_message("📭 Nenhuma mensagem agendada.", ephemeral=True)
            return
        lines = [
            f"• `{s['id']}` — <#{s['channel_id']}> a cada **{s['interval_minutes']} min**: {s['message'][:60]}"
            for s in schedules
        ]
        embed = discord.Embed(title="🕰️ Mensagens Agendadas", description="\n".join(lines), color=discord.Color.dark_gold())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @chancelaria_group.command(name="remover_agendamento", description="Remove uma mensagem agendada pelo ID.")
    @app_commands.describe(job_id="ID exibido em /chancelaria listar_agendamentos")
    async def remover_agendamento(self, interaction: discord.Interaction, job_id: str):
        settings = await db.get_guild_settings(interaction.guild_id)
        schedules = settings.get("scheduled_messages", [])
        new_schedules = [s for s in schedules if s.get("id") != job_id.strip()]
        if len(new_schedules) == len(schedules):
            await interaction.response.send_message("❌ ID não encontrado.", ephemeral=True)
            return
        await db.update_guild(interaction.guild_id, "scheduled_messages", new_schedules)
        await interaction.response.send_message(f"🗑️ Agendamento `{job_id}` removido.", ephemeral=True)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        settings = await db.get_guild_settings(member.guild.id)
        channel_id = settings.get("welcome_channel")
        if not channel_id:
            return
        channel = member.guild.get_channel(channel_id)
        if not channel:
            return
        template = settings.get("welcome_message", "Bem-vindo, {usuario}!")
        text = template.format(
            usuario=member.mention,
            servidor=member.guild.name,
            membros=member.guild.member_count,
        )
        embed = discord.Embed(
            title="🕊️ Novo Irmão no Mosteiro",
            description=text,
            color=discord.Color.dark_gold(),
        )
        if member.display_avatar:
            embed.set_thumbnail(url=member.display_avatar.url)
        await channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member: discord.Member):
        if member.bot:
            return
        settings = await db.get_guild_settings(member.guild.id)
        channel_id = settings.get("farewell_channel")
        if not channel_id:
            return
        channel = member.guild.get_channel(channel_id)
        if not channel:
            return
        template = settings.get("farewell_message", "{usuario} partiu do mosteiro.")
        text = template.format(
            usuario=member.name,
            servidor=member.guild.name,
            membros=member.guild.member_count,
        )
        await channel.send(text)

    @tasks.loop(minutes=1)
    async def scheduled_loop(self):
        now = time.time()
        for guild in self.bot.guilds:
            settings = await db.get_guild_settings(guild.id)
            schedules = settings.get("scheduled_messages", [])
            updated = False
            for job in schedules:
                interval_sec = int(job.get("interval_minutes", 60)) * 60
                if now - float(job.get("last_run", 0)) >= interval_sec:
                    channel = guild.get_channel(job["channel_id"])
                    if channel:
                        try:
                            await channel.send(job["message"])
                        except discord.HTTPException:
                            pass
                    job["last_run"] = now
                    updated = True
            if updated:
                await db.update_guild(guild.id, "scheduled_messages", schedules)

    @scheduled_loop.before_loop
    async def before_scheduled_loop(self):
        await self.bot.wait_until_ready()

    @commands.command(name="clear", aliases=["limpar"])
    @is_ctx_admin_or_owner()
    async def clear_messages(self, ctx: commands.Context, quantidade: int = 0):
        """Apaga N mensagens recentes do canal atual (ex: !clear 10)."""
        if quantidade < 1 or quantidade > 100:
            await ctx.send("❌ Informe uma quantidade entre **1** e **100** (ex: `!clear 10`).", delete_after=5)
            return

        try:
            try:
                await ctx.message.delete()
            except discord.HTTPException:
                pass
            deleted = await ctx.channel.purge(limit=quantidade)
            await ctx.send(f"🧹 **{len(deleted)}** mensagem(ns) apagada(s).", delete_after=4)
        except discord.Forbidden:
            await ctx.send("❌ Não tenho permissão de **Gerenciar Mensagens** neste canal.", delete_after=5)
        except discord.HTTPException as e:
            await ctx.send(f"❌ Erro ao apagar mensagens: `{e}`", delete_after=5)

    @clear_messages.error
    async def clear_messages_error(self, ctx: commands.Context, error: commands.CommandError):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ Você precisa da permissão **Gerenciar Mensagens** para usar `!clear`.", delete_after=5)
        elif isinstance(error, commands.BadArgument):
            await ctx.send("❌ Uso correto: `!clear <número>` (ex: `!clear 10`).", delete_after=5)


async def setup(bot: commands.Bot):
    await bot.add_cog(Chancelaria(bot))
