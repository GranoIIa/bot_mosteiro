import discord
from discord import app_commands
from discord.ext import commands


class EmbedModal(discord.ui.Modal, title="Criar Comunicado do Mosteiro"):
    titulo = discord.ui.TextInput(label="Título", placeholder="Ex: Edito do Abade", required=True)
    descricao = discord.ui.TextInput(
        label="Descrição",
        style=discord.TextStyle.paragraph,
        placeholder="Escreva o comunicado aqui...",
        required=True,
    )
    thumbnail = discord.ui.TextInput(label="URL Thumbnail (opcional)", placeholder="https://...", required=False)
    banner = discord.ui.TextInput(label="URL Banner (opcional)", placeholder="https://...", required=False)
    cor_hex = discord.ui.TextInput(
        label="Cor Hex (ex: C28E36)",
        placeholder="C28E36",
        min_length=6,
        max_length=6,
        required=False,
    )

    async def on_submit(self, interaction: discord.Interaction):
        cor = (self.cor_hex.value or "C28E36").lstrip("#")
        try:
            cor_int = int(cor, 16)
        except ValueError:
            cor_int = 0xC28E36

        embed = discord.Embed(title=self.titulo.value, description=self.descricao.value, color=cor_int)
        if self.thumbnail.value:
            embed.set_thumbnail(url=self.thumbnail.value)
        if self.banner.value:
            embed.set_image(url=self.banner.value)

        embed.set_footer(text=f"Publicado por {interaction.user.display_name}")
        await interaction.response.send_message("✅ Comunicado publicado!", ephemeral=True)
        await interaction.channel.send(embed=embed)


class EmbedMaker(commands.Cog):
    """Criador de embeds personalizados."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="gerar_embed", description="Abre o formulário para publicar um comunicado em embed.")
    @app_commands.default_permissions(administrator=True)
    async def gerar_embed(self, interaction: discord.Interaction):
        await interaction.response.send_modal(EmbedModal())


async def setup(bot: commands.Bot):
    await bot.add_cog(EmbedMaker(bot))
