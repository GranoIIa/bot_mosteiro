# Bot do Mosteiro (Unificado)

Bot em **Python (`discord.py`)** projetado para unificar as funções de 4 bots em um único serviço:

- **Chancelaria / Cargos (Carl-bot):** `/autorole`, `/painel_verificacao`, `/cargo adicionar|remover|painel`, `/config reaction_role_add`, `/chancelaria boas_vindas|despedida|agendar`, `/gerar_embed` e logs em `/config logchannel`.
- **Audiências & Tickets (Ticket Tool):** `/audiencia configurar`, `/audiencia painel`, `/audiencia adicionar|remover` com categorias (*Audiência com o Abade*, *Denúncia*, *Petição*, *Atendimento Privado*) e transcrição automática em `.txt`.
- **Noviciado & Recrutamento (Appy):** `/recrutamento configurar`, `/recrutamento painel` com formulários para *Ingresso no Mosteiro* e *Recrutamento do Clero*, avaliação do Conselho (*Aprovar*, *Recusar*, *Entrevista*) e entrega automática de cargo.
- **Música & Ambientação (Jockie Music):** `/play`, `/pause`, `/resume`, `/skip`, `/stop`, `/queue`, `/volume`, `/loop` e `/ambiente` (presets de cantos gregorianos e ambientação medieval).

## Configuração Rápida

1. Copie `.env.example` para `.env` e preencha `DISCORD_TOKEN`.
2. No **Discord Developer Portal**, habilite as intents **Server Members Intent** e **Message Content Intent**.
3. Execute `Iniciar Bot.bat` (ou `.venv\Scripts\python.exe bot.py`).
4. No Discord, envie `!sync` para registrar os Slash Commands.
