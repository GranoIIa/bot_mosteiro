import os
import sys
import discord
from discord.ext import commands
from dotenv import load_dotenv

# Configuração de encoding para Windows
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

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
        super().__init__(command_prefix="!", intents=intents)

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
