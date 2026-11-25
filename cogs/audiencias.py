import asyncio
import datetime
import io
import discord
from discord import app_commands
from discord.app_commands import Choice
from discord.ext import commands
from database.connection import db
from utils.permissions import is_admin_or_owner

TICKET_TYPES = {
    "abade": {"label": "Audiência com o Abade", "category_name": "👑 Audiências com o Abade", "emoji": "👑", "prefix": "abade", "desc": "Assuntos diretos com o Abade."},
    "denuncia": {"label": "Denúncia", "category_name": "⚖️ Denúncias", "emoji": "⚖️", "prefix": "denuncia", "desc": "Relatar infrações ou condutas graves."},
    "peticao": {"label": "Petição", "category_name": "📜 Petições", "emoji": "📜", "prefix": "peticao", "desc": "Solicitações formais ao Conselho."},
    "privado": {"label": "Atendimento Privado", "category_name": "🕯️ Atendimentos Privados", "emoji": "🕯️", "prefix": "privado", "desc": "Dúvidas ou suporte reservado."},
}


async def ensure_ticket_categories(guild: discord.Guild) -> dict:
    """Garante que exista uma categoria no Discord para cada tipo de ticket."""
    settings = await db.get_guild_settings(guild.id)
    tcfg = settings["ticket_config"]
    changed = False

    for key, info in TICKET_TYPES.items():
        cat_cfg = tcfg["categories"].setdefault(key, {"category_id": None, "role_ids": []})
        cat_id = cat_cfg.get("category_id")
        category = guild.get_channel(cat_id) if cat_id else None

        if category is None:
            category = discord.utils.get(guild.categories, name=info["category_name"])
        if category is None:
            try:
                overwrites = {
                    guild.default_role: discord.PermissionOverwrite(view_channel=False),
                    guild.me: discord.PermissionOverwrite(view_channel=True, manage_channels=True),
                }
                category = await guild.create_category(
                    name=info["category_name"],
                    overwrites=overwrites,
                    reason="Configuração automática das categorias de atendimento",
                )
            except discord.Forbidden:
                continue

        if cat_cfg.get("category_id") != category.id:
            cat_cfg["category_id"] = category.id
            changed = True

    if changed:
        await db.update_guild(guild.id, "ticket_config", tcfg)
    return tcfg


class TicketControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🙋 Assumir", style=discord.ButtonStyle.primary, custom_id="mosteiro:ticket_claim")
    async def claim_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        ticket = await db.get_ticket(interaction.channel_id)
        if not ticket:
            await interaction.response.send_message("❌ Este canal não é um ticket registrado.", ephemeral=True)
            return

        ticket["claimed_by"] = interaction.user.id
        await db.save_ticket(interaction.channel_id, ticket)
        await interaction.response.send_message(f"🙋 Atendimento assumido por {interaction.user.mention}.")

    @discord.ui.button(label="🔒 Encerrar", style=discord.ButtonStyle.danger, custom_id="mosteiro:ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        ticket = await db.get_ticket(interaction.channel_id)
        if not ticket:
            await interaction.followup.send("❌ Ticket não encontrado no registro.", ephemeral=True)
            return

        await interaction.followup.send("🔒 Gerando transcrição e encerrando este atendimento em 5 segundos...")

        lines = [
            f"=== TRANSCRIÇÃO DE TICKET #{ticket.get('number', '?')} ===",
            f"Categoria: {TICKET_TYPES.get(ticket.get('type', ''), {}).get('label', ticket.get('type'))}",
            f"Autor ID: {ticket.get('author_id')}",
            f"Encerrado por: {interaction.user} ({interaction.user.id})",
            "=" * 50,
            "",
        ]
        async for msg in interaction.channel.history(limit=500, oldest_first=True):
            ts = msg.created_at.strftime("%Y-%m-%d %H:%M:%S")
            content = msg.content or "[Sem texto]"
            if msg.attachments:
                att_urls = ", ".join(a.url for a in msg.attachments)
                content += f" [Anexos: {att_urls}]"
            lines.append(f"[{ts}] {msg.author} ({msg.author.id}): {content}")

        transcript_bytes = "\n".join(lines).encode("utf-8")
        settings = await db.get_guild_settings(interaction.guild_id)
        log_channel_id = settings.get("ticket_config", {}).get("log_channel") or settings.get("log_channel")
        if log_channel_id:
            log_channel = interaction.guild.get_channel(log_channel_id)
            if log_channel:
                file = discord.File(
                    io.BytesIO(transcript_bytes),
                    filename=f"transcricao-{interaction.channel.name}.txt",
                )
                embed = discord.Embed(
                    title=f"📜 Transcrição — {interaction.channel.name}",
                    description=(
                        f"**Aberto por:** <@{ticket.get('author_id')}>\n"
                        f"**Encerrado por:** {interaction.user.mention}\n"
                        f"**Tipo:** {TICKET_TYPES.get(ticket.get('type', ''), {}).get('label', 'N/A')}"
                    ),
                    color=discord.Color.dark_gold(),
                    timestamp=datetime.datetime.now(datetime.timezone.utc),
                )
                await log_channel.send(embed=embed, file=file)

        await db.delete_ticket(interaction.channel_id)
        await asyncio.sleep(5)
        try:
            await interaction.channel.delete(reason=f"Ticket encerrado por {interaction.user}")
        except discord.HTTPException:
            pass


class TicketCategorySelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=info["label"], value=key, description=info["desc"], emoji=info["emoji"])
            for key, info in TICKET_TYPES.items()
        ]
        super().__init__(
            placeholder="Selecione o tipo de audiência ou atendimento...",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="mosteiro:ticket_select",
        )

    async def callback(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            ticket_type = self.values[0]
            info = TICKET_TYPES[ticket_type]

            open_tickets = await db.list_open_tickets(interaction.guild_id, interaction.user.id)
            for t in open_tickets:
                if t.get("type") == ticket_type and interaction.guild.get_channel(t["channel_id"]):
                    await interaction.followup.send(
                        f"⚠️ Você já possui um atendimento aberto em <#{t['channel_id']}>.",
                        ephemeral=True,
                    )
                    return

            tcfg = await ensure_ticket_categories(interaction.guild)
            cat_cfg = tcfg.get("categories", {}).get(ticket_type, {})
            category = interaction.guild.get_channel(cat_cfg.get("category_id")) if cat_cfg.get("category_id") else None

            overwrites = {
                interaction.guild.default_role: discord.PermissionOverwrite(view_channel=False),
                interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, read_message_history=True),
                interaction.guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
            }

            mention_roles = []
            for role_id in cat_cfg.get("role_ids", []):
                role = interaction.guild.get_role(role_id)
                if role:
                    overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
                    mention_roles.append(role.mention)

            ticket_num = await db.next_ticket_number(interaction.guild_id)
            channel_name = f"{info['prefix']}-{ticket_num:04d}"

            try:
                channel = await interaction.guild.create_text_channel(
                    name=channel_name,
                    category=category,
                    overwrites=overwrites,
                    reason=f"Ticket {info['label']} aberto por {interaction.user}",
                )
            except discord.Forbidden:
                await interaction.followup.send("❌ Sem permissão para criar canais de atendimento.", ephemeral=True)
                return

            await db.save_ticket(
                channel.id,
                {
                    "channel_id": channel.id,
                    "guild_id": interaction.guild_id,
                    "author_id": interaction.user.id,
                    "type": ticket_type,
                    "number": ticket_num,
                    "claimed_by": None,
                },
            )

            embed = discord.Embed(
                title=f"{info['emoji']} {info['label']} #{ticket_num:04d}",
                description=(
                    f"Saudações, {interaction.user.mention}.\n"
                    "Descreva sua solicitação com clareza para que a equipe responsável possa atendê-lo."
                ),
                color=discord.Color.dark_gold(),
            )
            mentions = " ".join([interaction.user.mention] + mention_roles)
            await channel.send(content=mentions, embed=embed, view=TicketControlView())
            await interaction.followup.send(f"✅ Atendimento aberto em {channel.mention}.", ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"❌ Erro ao abrir atendimento: `{e}`", ephemeral=True)


class TicketPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(TicketCategorySelect())


class Audiencias(commands.Cog):
    """Sistema de tickets para audiências, denúncias, petições e atendimentos privados."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    audiencia_group = app_commands.Group(
        name="audiencia",
        description="Gerenciamento de audiências e atendimentos privados",
    )

    async def cog_load(self):
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(TicketControlView())

    @commands.Cog.listener()
    async def on_ready(self):
        for guild in self.bot.guilds:
            try:
                await ensure_ticket_categories(guild)
            except Exception as e:
                print(f"⚠️ Erro ao criar categorias de ticket em {guild.name}: {e}")

    @audiencia_group.command(name="configurar", description="Configura categoria, cargo responsável e canal de logs.")
    @is_admin_or_owner()
    @app_commands.choices(
        tipo=[
            Choice(name="Audiência com o Abade", value="abade"),
            Choice(name="Denúncia", value="denuncia"),
            Choice(name="Petição", value="peticao"),
            Choice(name="Atendimento Privado", value="privado"),
        ]
    )
    @app_commands.describe(
        tipo="Tipo de atendimento",
        categoria="Categoria onde os canais serão criados",
        cargo_responsavel="Cargo que terá acesso a esse tipo de ticket",
        canal_logs="Canal opcional para envio das transcrições",
    )
    async def configurar(
        self,
        interaction: discord.Interaction,
        tipo: Choice[str],
        categoria: discord.CategoryChannel,
        cargo_responsavel: discord.Role,
        canal_logs: discord.TextChannel = None,
    ):
        settings = await db.get_guild_settings(interaction.guild_id)
        tcfg = settings["ticket_config"]
        tcfg["categories"][tipo.value] = {
            "category_id": categoria.id,
            "role_ids": [cargo_responsavel.id],
        }
        if canal_logs:
            tcfg["log_channel"] = canal_logs.id
        await db.update_guild(interaction.guild_id, "ticket_config", tcfg)
        await interaction.response.send_message(
            f"✅ **{tipo.name}** configurado na categoria **{categoria.name}** para {cargo_responsavel.mention}.",
            ephemeral=True,
        )

    @audiencia_group.command(name="painel", description="Publica o painel de abertura de audiências e tickets.")
    @is_admin_or_owner()
    async def painel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="⚖️ Audiências & Atendimentos do Mosteiro",
            description=(
                "Selecione abaixo o tipo de atendimento desejado:\n\n"
                "👑 **Audiência com o Abade** — Assuntos diretos com a liderança.\n"
                "⚖️ **Denúncia** — Relatar condutas ou infrações.\n"
                "📜 **Petição** — Solicitações formais ao Conselho.\n"
                "🕯️ **Atendimento Privado** — Suporte reservado."
            ),
            color=discord.Color.dark_gold(),
        )
        await interaction.response.send_message("✅ Painel de audiências publicado!", ephemeral=True)
        await interaction.channel.send(embed=embed, view=TicketPanelView())

    @audiencia_group.command(name="adicionar", description="Adiciona um membro ao ticket atual.")
    @app_commands.describe(membro="Membro a adicionar")
    async def adicionar(self, interaction: discord.Interaction, membro: discord.Member):
        if not await db.get_ticket(interaction.channel_id):
            await interaction.response.send_message("❌ Use este comando dentro de um ticket.", ephemeral=True)
            return
        await interaction.channel.set_permissions(membro, view_channel=True, send_messages=True, read_message_history=True)
        await interaction.response.send_message(f"➕ {membro.mention} foi adicionado ao atendimento.")

    @audiencia_group.command(name="remover", description="Remove um membro do ticket atual.")
    @app_commands.describe(membro="Membro a remover")
    async def remover(self, interaction: discord.Interaction, membro: discord.Member):
        if not await db.get_ticket(interaction.channel_id):
            await interaction.response.send_message("❌ Use este comando dentro de um ticket.", ephemeral=True)
            return
        await interaction.channel.set_permissions(membro, overwrite=None)
        await interaction.response.send_message(f"➖ {membro.mention} foi removido do atendimento.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Audiencias(bot))
