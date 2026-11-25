import os
import sys
import ctypes.util
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from utils.permissions import OWNER_IDS

# Configuração de encoding para Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# Carrega libopus (necessário para áudio de voz)
def _load_opus():
    if discord.opus.is_loaded():
        return True

    # Tenta caminhos conhecidos
    _opus_candidates = [
        ctypes.util.find_library("opus"),
        "libopus.so.0",
        "libopus.so",
        "opus",
        "/usr/lib/x86_64-linux-gnu/libopus.so.0",
        "/usr/lib/aarch64-linux-gnu/libopus.so.0",
        "/usr/lib/libopus.so.0",
        "/usr/local/lib/libopus.so.0",
        "/app/libopus.so.0",
    ]
    for _lib in filter(None, _opus_candidates):
        try:
            discord.opus.load_opus(_lib)
            print(f"🔊 Opus carregado: {_lib}")
            return True
        except Exception:
            continue

    # Fallback: tenta instalar via apt-get e recarregar
    if sys.platform == "linux":
        import subprocess
        for pkg in ["libopus0", "libopus-dev", "opus-tools"]:
            try:
                subprocess.run(["apt-get", "install", "-y", "-qq", pkg], capture_output=True, timeout=30)
            except Exception:
                pass
        # Tenta carregar de novo após instalar
        for _lib in filter(None, _opus_candidates):
            try:
                discord.opus.load_opus(_lib)
                print(f"🔊 Opus carregado (pós-install): {_lib}")
                return True
            except Exception:
                continue

    print("⚠️ AVISO: libopus não encontrada. Comandos de voz/música não funcionarão.")
    return False

_load_opus()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
_raw_token = os.getenv("DISCORD_TOKEN") or os.getenv("TOKEN")
TOKEN = _raw_token.strip().strip('"').strip("'") if _raw_token else None

intents = discord.Intents.default()
intents.message_content = True
intents.members = True


class MosteiroBot(commands.Bot):
    """Bot unificado do Mosteiro (Cargos, Audiências, Recrutamento e Música)."""

    def __init__(self):
        super().__init__(command_prefix="!", intents=intents, owner_ids=OWNER_IDS)

    async def setup_hook(self):
        cogs_dir = os.path.join(os.path.dirname(__file__), "cogs")
        os.makedirs(cogs_dir, exist_ok=True)

        for filename in sorted(os.listdir(cogs_dir)):
            if filename.endswith(".py") and not filename.startswith("__"):
                module_name = f"cogs.{filename[:-3]}"
                try:
                    await self.load_extension(module_name)
                    print(f"📦 Módulo carregado: {filename}")
                except Exception as e:
                    print(f"❌ Falha ao carregar {filename}: {e}")

    async def on_ready(self):
        print("---")
        print(f"✅ Logado como {self.user.name} (ID: {self.user.id})")
        print(f"📡 Conectado em {len(self.guilds)} servidores.")
        print("💡 Dica: Use !sync no Discord para atualizar os Slash Commands.")
        print("---")


bot = MosteiroBot()


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if isinstance(error, app_commands.MissingPermissions):
        msg = "❌ Você precisa de permissão de **Administrador** para usar este comando."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
        return
    raise error


@bot.command()
@commands.is_owner()
async def sync(ctx: commands.Context):
    """Sincroniza os Slash Commands manualmente para evitar rate limit no on_ready."""
    await ctx.send("⏳ Sincronizando comandos... Aguarde.")
    try:
        synced = await bot.tree.sync()
        await ctx.send(f"✅ Sucesso! {len(synced)} comandos Slash sincronizados globalmente.")
    except Exception as e:
        await ctx.send(f"❌ Erro ao sincronizar: {e}")


if __name__ == "__main__":
    if TOKEN and TOKEN != "seutokenaqui":
        bot.run(TOKEN)
    else:
        print("❌ ERRO: DISCORD_TOKEN inválido ou ausente. Configure no .env (local) ou nas Variáveis de Ambiente da Discloud (DISCORD_TOKEN).")
