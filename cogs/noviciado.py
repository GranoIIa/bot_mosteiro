import datetime
import uuid
import discord
from discord import app_commands
from discord.ext import commands
from database.connection import db
from utils.permissions import AdminGroup


class RejectReasonModal(discord.ui.Modal, title="Motivo da Recusa"):
    motivo = discord.ui.TextInput(
        label="Informe o motivo da recusa",
        style=discord.TextStyle.paragraph,
        placeholder="Será enviado ao candidato por mensagem privada.",
        required=True,
        max_length=500,
    )

    def __init__(self, app_id: str):
        super().__init__()
        self.app_id = app_id

    async def on_submit(self, interaction: discord.Interaction):
        app_doc = await db.get_application(self.app_id)
        if not app_doc:
            await interaction.response.send_message("❌ Ficha não encontrada.", ephemeral=True)
            return

        app_doc["status"] = "rejected"
        app_doc["reviewed_by"] = interaction.user.id
        app_doc["reason"] = self.motivo.value
        await db.save_application(self.app_id, app_doc)

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.red()
        embed.set_footer(text=f"❌ Recusado por {interaction.user.display_name} | Motivo: {self.motivo.value[:100]}")
        await interaction.message.edit(embed=embed, view=None)

        user = interaction.guild.get_member(app_doc["user_id"])
        if user:
            try:
                await user.send(
                    f"❌ Sua candidatura para **{app_doc['type_label']}** em **{interaction.guild.name}** foi recusada.\n"
                    f"**Motivo:** {self.motivo.value}"
                )
            except discord.Forbidden:
                pass

        await interaction.response.send_message("Candidatura recusada e candidato notificado.", ephemeral=True)


class ApplicationReviewView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    def _extract_app_id(self, message: discord.Message) -> str | None:
        if not message.embeds or not message.embeds[0].footer or not message.embeds[0].footer.text:
            return None
        footer = message.embeds[0].footer.text
        if "ID:" in footer:
            return footer.split("ID:")[-1].strip()
        return None

    @discord.ui.button(label="✅ Aprovar", style=discord.ButtonStyle.green, custom_id="mosteiro:app_approve")
    async def approve_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        app_id = self._extract_app_id(interaction.message)
        app_doc = await db.get_application(app_id) if app_id else None
        if not app_doc:
            await interaction.response.send_message("❌ Ficha não encontrada.", ephemeral=True)
            return

        settings = await db.get_guild_settings(interaction.guild_id)
        app_cfg = settings.get("app_config", {})
        role_key = "mosteiro_role_id" if app_doc["app_type"] == "mosteiro" else "clero_role_id"
        role_id = app_cfg.get(role_key)

        member = interaction.guild.get_member(app_doc["user_id"])
        role_note = ""
        if member and role_id:
            role = interaction.guild.get_role(role_id)
            if role:
                try:
                    await member.add_roles(role, reason=f"Candidatura aprovada por {interaction.user}")
                    role_note = f" (Cargo {role.name} entregue)"
                except discord.Forbidden:
                    role_note = " (Erro de permissão ao entregar cargo)"

        app_doc["status"] = "approved"
        app_doc["reviewed_by"] = interaction.user.id
        await db.save_application(app_id, app_doc)

        embed = interaction.message.embeds[0]
        embed.color = discord.Color.green()
        embed.set_footer(text=f"✅ Aprovado por {interaction.user.display_name}{role_note}")
        await interaction.message.edit(embed=embed, view=None)

        if member:
            try:
                await member.send(
                    f"🎉 Parabéns! Sua candidatura para **{app_doc['type_label']}** em **{interaction.guild.name}** foi **aprovada**!"
                )
            except discord.Forbidden:
                pass

        await interaction.response.send_message(f"✅ Candidatura aprovada{role_note}.", ephemeral=True)

    @discord.ui.button(label="❌ Recusar", style=discord.ButtonStyle.danger, custom_id="mosteiro:app_reject")
    async def reject_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        app_id = self._extract_app_id(interaction.message)
        if not app_id:
            await interaction.response.send_message("❌ Ficha não encontrada.", ephemeral=True)
            return
        await interaction.response.send_modal(RejectReasonModal(app_id))

    @discord.ui.button(label="🗣️ Entrevista", style=discord.ButtonStyle.secondary, custom_id="mosteiro:app_interview")
    async def interview_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        app_id = self._extract_app_id(interaction.message)
        app_doc = await db.get_application(app_id) if app_id else None
        if not app_doc:
            await interaction.response.send_message("❌ Ficha não encontrada.", ephemeral=True)
            return

        member = interaction.guild.get_member(app_doc["user_id"])
        if member:
            try:
                await member.send(
                    f"🗣️ Sua candidatura para **{app_doc['type_label']}** em **{interaction.guild.name}** avançou para **entrevista**. "
                    "Aguarde ou procure um responsável no servidor."
                )
            except discord.Forbidden:
                pass
        await interaction.response.send_message(
            f"🗣️ {interaction.user.mention} marcou o candidato (<@{app_doc['user_id']}>) para entrevista."
        )


async def _submit_application(
    interaction: discord.Interaction,
    app_type: str,
    type_label: str,
    answers: list[tuple[str, str]],
):
    settings = await db.get_guild_settings(interaction.guild_id)
    review_channel_id = settings.get("app_config", {}).get("review_channel")
    if not review_channel_id:
        await interaction.response.send_message(
            "❌ Canal de avaliação não configurado. Peça à administração para usar `/recrutamento configurar`.",
            ephemeral=True,
        )
        return

    review_channel = interaction.guild.get_channel(review_channel_id)
    if not review_channel:
        await interaction.response.send_message("❌ Canal de avaliação não encontrado.", ephemeral=True)
        return

    app_id = str(uuid.uuid4())[:8]
    await db.save_application(
        app_id,
        {
            "id": app_id,
            "guild_id": interaction.guild_id,
            "user_id": interaction.user.id,
            "app_type": app_type,
            "type_label": type_label,
            "answers": answers,
            "status": "pending",
        },
    )

    embed = discord.Embed(
        title=f"📜 Nova Ficha — {type_label}",
        description=f"**Candidato:** {interaction.user.mention} (`{interaction.user.id}`)",
        color=discord.Color.dark_gold(),
        timestamp=datetime.datetime.now(datetime.timezone.utc),
    )
    if interaction.user.display_avatar:
        embed.set_thumbnail(url=interaction.user.display_avatar.url)

    for question, answer in answers:
        embed.add_field(name=question, value=answer[:1024], inline=False)

    embed.set_footer(text=f"Aguardando avaliação | ID: {app_id}")
    await review_channel.send(embed=embed, view=ApplicationReviewView())
    await interaction.response.send_message(
        f"✅ Sua ficha para **{type_label}** foi enviada ao Conselho! Você será notificado por DM.",
        ephemeral=True,
    )


class MosteiroApplicationModal(discord.ui.Modal, title="Ingresso no Mosteiro"):
    nome = discord.ui.TextInput(label="Nome / Nickname", required=True, max_length=100)
    idade_disp = discord.ui.TextInput(label="Idade e Disponibilidade", placeholder="Ex: 20 anos, noites e fins de semana", required=True, max_length=120)
    experiencia = discord.ui.TextInput(label="Experiência em RP / Comunidade", style=discord.TextStyle.paragraph, required=True, max_length=500)
    motivacao = discord.ui.TextInput(label="Por que deseja ingressar no Mosteiro?", style=discord.TextStyle.paragraph, required=True, max_length=500)
    contribuicao = discord.ui.TextInput(label="Como pretende contribuir com a ordem?", style=discord.TextStyle.paragraph, required=True, max_length=400)

    async def on_submit(self, interaction: discord.Interaction):
        answers = [
            ("Nome / Nickname", self.nome.value),
            ("Idade e Disponibilidade", self.idade_disp.value),
            ("Experiência em RP / Comunidade", self.experiencia.value),
            ("Motivação", self.motivacao.value),
            ("Contribuição", self.contribuicao.value),
        ]
        await _submit_application(interaction, "mosteiro", "Ingresso no Mosteiro", answers)


class CleroApplicationModal(discord.ui.Modal, title="Recrutamento do Clero"):
    nome = discord.ui.TextInput(label="Nome / Nickname", required=True, max_length=100)
    funcao = discord.ui.TextInput(label="Função pretendida no Clero", placeholder="Ex: Noviço, Diácono, Escrivão, Mentor", required=True, max_length=100)
    experiencia = discord.ui.TextInput(label="Experiência prévia de liderança/mediação", style=discord.TextStyle.paragraph, required=True, max_length=500)
    disponibilidade = discord.ui.TextInput(label="Disponibilidade semanal", required=True, max_length=120)
    motivo = discord.ui.TextInput(label="Por que deseja servir ao Clero?", style=discord.TextStyle.paragraph, required=True, max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        answers = [
            ("Nome / Nickname", self.nome.value),
            ("Função Pretendida", self.funcao.value),
            ("Experiência Prévia", self.experiencia.value),
            ("Disponibilidade Semanal", self.disponibilidade.value),
            ("Vocação / Motivo", self.motivo.value),
        ]
        await _submit_application(interaction, "clero", "Recrutamento do Clero", answers)


class RecruitmentPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🕯️ Ingresso no Mosteiro", style=discord.ButtonStyle.primary, custom_id="mosteiro:app_mosteiro")
    async def btn_mosteiro(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(MosteiroApplicationModal())

    @discord.ui.button(label="✝️ Recrutamento do Clero", style=discord.ButtonStyle.success, custom_id="mosteiro:app_clero")
    async def btn_clero(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CleroApplicationModal())


class Noviciado(commands.Cog):
    """Formulários de ingresso no mosteiro e recrutamento do clero."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    recrutamento_group = AdminGroup(
        name="recrutamento",
        description="Configuração e painel de formulários do Mosteiro e Clero",
    )

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(RecruitmentPanelView())
        self.bot.add_view(ApplicationReviewView())

    @recrutamento_group.command(name="configurar", description="Define o canal de avaliação e os cargos entregues na aprovação.")
    @app_commands.describe(
        canal_avaliacao="Canal privado onde o Conselho avaliará as fichas",
        cargo_mosteiro="Cargo entregue ao aprovar ingresso no Mosteiro",
        cargo_clero="Cargo entregue ao aprovar recrutamento do Clero",
    )
    async def configurar(
        self,
        interaction: discord.Interaction,
        canal_avaliacao: discord.TextChannel,
        cargo_mosteiro: discord.Role = None,
        cargo_clero: discord.Role = None,
    ):
        settings = await db.get_guild_settings(interaction.guild_id)
        app_cfg = settings["app_config"]
        app_cfg["review_channel"] = canal_avaliacao.id
        if cargo_mosteiro:
            app_cfg["mosteiro_role_id"] = cargo_mosteiro.id
        if cargo_clero:
            app_cfg["clero_role_id"] = cargo_clero.id
        await db.update_guild(interaction.guild_id, "app_config", app_cfg)
        await interaction.response.send_message(
            f"✅ Recrutamento configurado! Fichas serão enviadas para {canal_avaliacao.mention}.",
            ephemeral=True,
        )

    @recrutamento_group.command(name="painel", description="Publica o painel de candidaturas no canal atual.")
    async def painel(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="📜 Recrutamento & Ingresso no Mosteiro",
            description=(
                "Escolha abaixo o formulário que deseja preencher:\n\n"
                "🕯️ **Ingresso no Mosteiro** — Para novos membros que desejam integrar a irmandade.\n"
                "✝️ **Recrutamento do Clero** — Para candidatos às funções clericais e de liderança."
            ),
            color=discord.Color.dark_gold(),
        )
        await interaction.response.send_message("✅ Painel de recrutamento publicado!", ephemeral=True)
        await interaction.channel.send(embed=embed, view=RecruitmentPanelView())


async def setup(bot: commands.Bot):
    await bot.add_cog(Noviciado(bot))
