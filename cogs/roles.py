import random
import string
import discord
from discord import app_commands
from discord.ext import commands
from database.connection import db
from utils.permissions import AdminGroup, is_admin_or_owner


class CaptchaModal(discord.ui.Modal, title="Verificação do Mosteiro"):
    def __init__(self, expected_code: str):
        super().__init__()
        self.expected_code = expected_code
        self.captcha_input = discord.ui.TextInput(
            label=f"Digite o código exato: {expected_code}",
            style=discord.TextStyle.short,
            placeholder="Digite os 5 caracteres acima",
            required=True,
            max_length=10,
        )
        self.add_item(self.captcha_input)

    async def on_submit(self, interaction: discord.Interaction):
        if self.captcha_input.value.strip().upper() != self.expected_code.upper():
            await interaction.response.send_message("❌ Código incorreto. Tente novamente.", ephemeral=True)
            return

        settings = await db.get_guild_settings(interaction.guild_id)
        verify_role_id = settings.get("verify_role")
        if not verify_role_id:
            await interaction.response.send_message(
                "❌ Cargo de verificação não configurado. Use `/config cargo_verificado`.",
                ephemeral=True,
            )
            return

        role = interaction.guild.get_role(verify_role_id)
        if not role:
            await interaction.response.send_message("❌ O cargo de verificação não existe mais.", ephemeral=True)
            return

        if role in interaction.user.roles:
            await interaction.response.send_message("🛡️ Você já está verificado.", ephemeral=True)
            return

        try:
            await interaction.user.add_roles(role, reason="Verificação concluída via painel.")
            await interaction.response.send_message(
                f"🕊️ Bem-vindo! Você recebeu o cargo **{role.name}**.",
                ephemeral=True,
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ Sem permissão para atribuir o cargo. Verifique a hierarquia de cargos do bot.",
                ephemeral=True,
            )


class VerificationView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="✅ Verificar-se",
        style=discord.ButtonStyle.green,
        custom_id="mosteiro:verify_button",
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=5))
        await interaction.response.send_modal(CaptchaModal(expected_code=code))


class RoleSelect(discord.ui.Select):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(
            placeholder="Escolha seus cargos...",
            min_values=0,
            max_values=max(1, len(options)),
            options=options,
            custom_id="mosteiro:role_select",
        )

    async def callback(self, interaction: discord.Interaction):
        panel_roles = [int(opt.value) for opt in self.options]
        selected_ids = {int(v) for v in self.values}

        added, removed = [], []
        for role_id in panel_roles:
            role = interaction.guild.get_role(role_id)
            if not role:
                continue
            has_role = role in interaction.user.roles
            try:
                if role_id in selected_ids and not has_role:
                    await interaction.user.add_roles(role, reason="Auto-cargo via painel")
                    added.append(role.name)
                elif role_id not in selected_ids and has_role:
                    await interaction.user.remove_roles(role, reason="Auto-cargo via painel")
                    removed.append(role.name)
            except discord.Forbidden:
                await interaction.response.send_message(
                    f"❌ Não tenho permissão para gerenciar o cargo **{role.name}**.",
                    ephemeral=True,
                )
                return

        parts = []
        if added:
            parts.append(f"➕ Adicionados: **{', '.join(added)}**")
        if removed:
            parts.append(f"➖ Removidos: **{', '.join(removed)}**")
        msg = "\n".join(parts) if parts else "Nenhuma alteração nos seus cargos."
        await interaction.response.send_message(msg, ephemeral=True)


class RolePanelView(discord.ui.View):
    def __init__(self, options: list[discord.SelectOption]):
        super().__init__(timeout=None)
        self.add_item(RoleSelect(options))


class Roles(commands.Cog):
    """Gerenciamento de cargos (autorole, verificação, reaction roles e painéis)."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    cargo_group = AdminGroup(
        name="cargo",
        description="Gerenciamento de painéis de auto-cargo",
    )

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(VerificationView())
        # Re-registra painéis de cargos salvos para persistirem após reinício
        for guild in self.bot.guilds:
            settings = await db.get_guild_settings(guild.id)
            panels = settings.get("role_panels", {})
            for panel_data in panels.values():
                options = []
                for item in panel_data.get("roles", []):
                    role = guild.get_role(item["role_id"])
                    if role:
                        options.append(
                            discord.SelectOption(
                                label=item.get("label") or role.name,
                                value=str(role.id),
                                description=item.get("description") or None,
                                emoji=item.get("emoji") or None,
                            )
                        )
                if options:
                    self.bot.add_view(RolePanelView(options[:25]))

    @app_commands.command(name="autorole", description="Define o cargo automático ao entrar no servidor.")
    @app_commands.describe(cargo="Cargo inicial (deixe vazio para desativar)")
    @is_admin_or_owner()
    async def autorole(self, interaction: discord.Interaction, cargo: discord.Role = None):
        if cargo:
            await db.update_guild(interaction.guild_id, "autorole", cargo.id)
            await interaction.response.send_message(f"✅ Auto-role definido para {cargo.mention}.", ephemeral=True)
        else:
            await db.unset_guild(interaction.guild_id, "autorole")
            await interaction.response.send_message("🔴 Auto-role desativado.", ephemeral=True)

    @app_commands.command(name="painel_verificacao", description="Envia o painel de verificação humana com captcha.")
    @is_admin_or_owner()
    async def painel_verificacao(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title="🛡️ Portões do Mosteiro — Verificação",
            description="Clique no botão abaixo e informe o código para confirmar que você é humano e liberar o acesso.",
            color=discord.Color.dark_gold(),
        )
        await interaction.response.send_message("✅ Painel enviado!", ephemeral=True)
        await interaction.channel.send(embed=embed, view=VerificationView())

    @cargo_group.command(name="adicionar", description="Adiciona um cargo ao catálogo do painel de auto-cargo.")
    @app_commands.describe(cargo="Cargo selecionável", descricao="Descrição curta", emoji="Emoji opcional")
    async def cargo_adicionar(
        self,
        interaction: discord.Interaction,
        cargo: discord.Role,
        descricao: str = "",
        emoji: str = None,
    ):
        settings = await db.get_guild_settings(interaction.guild_id)
        panels = settings.get("role_panels", {})
        default_panel = panels.setdefault("default", {"roles": []})
        default_panel["roles"] = [r for r in default_panel["roles"] if r["role_id"] != cargo.id]
        default_panel["roles"].append(
            {
                "role_id": cargo.id,
                "label": cargo.name[:100],
                "description": descricao[:100],
                "emoji": emoji.strip() if emoji else None,
            }
        )
        await db.update_guild(interaction.guild_id, "role_panels", panels)
        await interaction.response.send_message(f"✅ Cargo {cargo.mention} adicionado ao painel.", ephemeral=True)

    @cargo_group.command(name="remover", description="Remove um cargo do catálogo do painel de auto-cargo.")
    @app_commands.describe(cargo="Cargo para remover")
    async def cargo_remover(self, interaction: discord.Interaction, cargo: discord.Role):
        settings = await db.get_guild_settings(interaction.guild_id)
        panels = settings.get("role_panels", {})
        default_panel = panels.get("default", {"roles": []})
        before = len(default_panel["roles"])
        default_panel["roles"] = [r for r in default_panel["roles"] if r["role_id"] != cargo.id]
        panels["default"] = default_panel
        await db.update_guild(interaction.guild_id, "role_panels", panels)
        if len(default_panel["roles"]) < before:
            await interaction.response.send_message(f"🗑️ Cargo {cargo.mention} removido do painel.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ Esse cargo não estava no painel.", ephemeral=True)

    @cargo_group.command(name="painel", description="Publica o painel interativo de escolha de cargos no canal atual.")
    @app_commands.describe(titulo="Título do painel", descricao="Texto explicativo")
    async def cargo_painel(
        self,
        interaction: discord.Interaction,
        titulo: str = "📜 Chancelaria — Escolha seus Cargos",
        descricao: str = "Selecione no menu abaixo os cargos que deseja receber ou remover.",
    ):
        settings = await db.get_guild_settings(interaction.guild_id)
        roles_cfg = settings.get("role_panels", {}).get("default", {}).get("roles", [])
        options = []
        for item in roles_cfg[:25]:
            role = interaction.guild.get_role(item["role_id"])
            if role:
                options.append(
                    discord.SelectOption(
                        label=item.get("label") or role.name,
                        value=str(role.id),
                        description=item.get("description") or None,
                        emoji=item.get("emoji") or None,
                    )
                )
        if not options:
            await interaction.response.send_message(
                "❌ Nenhum cargo configurado ainda. Use `/cargo adicionar` primeiro.",
                ephemeral=True,
            )
            return

        embed = discord.Embed(title=titulo, description=descricao, color=discord.Color.dark_gold())
        await interaction.response.send_message("✅ Painel de cargos publicado!", ephemeral=True)
        await interaction.channel.send(embed=embed, view=RolePanelView(options))

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        if member.bot:
            return
        settings = await db.get_guild_settings(member.guild.id)
        autorole_id = settings.get("autorole")
        if autorole_id:
            role = member.guild.get_role(autorole_id)
            if role:
                try:
                    await member.add_roles(role, reason="AutoRole ao entrar")
                except discord.Forbidden:
                    pass

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload, "add")

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent):
        await self._handle_reaction(payload, "remove")

    async def _handle_reaction(self, payload: discord.RawReactionActionEvent, action: str):
        if not payload.guild_id:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if not guild:
            return
        member = guild.get_member(payload.user_id)
        if not member or member.bot:
            return

        settings = await db.get_guild_settings(guild.id)
        for rr in settings.get("reaction_roles", []):
            if rr["message_id"] == payload.message_id and rr["emoji"] == str(payload.emoji):
                role = guild.get_role(rr["role_id"])
                if not role:
                    continue
                try:
                    if action == "add" and role not in member.roles:
                        await member.add_roles(role, reason="Reaction Role")
                    elif action == "remove" and role in member.roles:
                        await member.remove_roles(role, reason="Reaction Role removida")
                except discord.Forbidden:
                    pass


async def setup(bot: commands.Bot):
    await bot.add_cog(Roles(bot))
