import asyncio
import datetime
import os
import random
import discord
from discord.ext import commands
from flask import Flask
from threading import Thread

# Configuração do Servidor Web Flask para o Render / UptimeRobot
app = Flask('')

@app.route('/')
def home():
    return "Bot de Partidas Online!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# Configuração do Bot do Discord
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

fila_1v1 = []
fila_pula_contra = []
fila_duplas_inscritos = []  # Lista dos capitães/representantes inscritos no painel 2
ranking_vitorias = {}
ranking_derrotas = {}
admins_em_servico = set()  # Guarda os IDs dos administradores em serviço

LOG_CHANNEL_NAME = "logs-partidas"
painel_mensagem_ref = None  # Guarda a referência della mensagem do painel principal
painel2_mensagem_ref = None # Guarda a referência da mensagem do painel 2 (duplas)


class FilaView(discord.ui.View):

  def __init__(self):
    super().__init__(timeout=None)

  def gerar_embed(self, bot_user=None):
    embed = discord.Embed(
        title="🎮 Sistema de Partidas",
        description="Clique nos botões abaixo para entrar ou sair das filas.",
        color=discord.Color.blurple(),
    )

    # --- TOP 3 VITÓRIAS (Esquerda) ---
    top_vitorias = sorted(ranking_vitorias.items(), key=lambda x: x, reverse=True)[:3]
    texto_vit = ""
    if not top_vitorias:
      texto_vit = "Nenhum ainda."
    else:
      medalhas = ["🥇", "🥈", "🥉"]
      for i, (uid, vit) in enumerate(top_vitorias):
        texto_vit += f"{medalhas[i]} <@{uid}>: **{vit}V**\n"

    embed.add_field(name="🏆 Top 3 Vitórias", value=texto_vit, inline=True)

    # --- TOP 3 DERROTAS (Direita) ---
    top_derrotas = sorted(ranking_derrotas.items(), key=lambda x: x, reverse=True)[:3]
    texto_der = ""
    if not top_derrotas:
      texto_der = "Nenhum ainda."
    else:
      medalhas = ["🥇", "🥈", "🥉"]
      for i, (uid, der) in enumerate(top_derrotas):
        texto_der += f"{medalhas[i]} <@{der}>: **{der}D**\n"

    embed.add_field(name="💀 Top 3 Derrotas", value=texto_der, inline=True)

    embed.add_field(name="\u200b", value="\u200b", inline=False)

    # --- FILAS ---
    texto_1v1 = (
        f"({len(fila_1v1)}/2)\n"
        if not fila_1v1
        else f"({len(fila_1v1)}/2)\n"
        + "\n".join([f"• {m.mention}" for m in fila_1v1])
    )
    embed.add_field(name="🎮 Fila 1v1", value=texto_1v1, inline=False)

    texto_pc = (
        f"({len(fila_pula_contra)}/2)\n"
        if not fila_pula_contra
        else f"({len(fila_pula_contra)}/2)\n"
        + "\n".join([f"• {m.mention}" for m in fila_pula_contra])
    )
    embed.add_field(
        name="⚡ Fila Pula Contra", value=texto_pc, inline=False
    )

    if bot_user and bot_user.avatar:
      embed.set_thumbnail(url=bot_user.avatar.url)

    return embed

  @discord.ui.button(
      label="Entrar 1v1",
      style=discord.ButtonStyle.primary,
      custom_id="btn_1v1",
  )
  async def callback_1v1(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user = interaction.user
    if user in fila_1v1:
      await interaction.response.defer()
      return

    if user in fila_pula_contra:
      fila_pula_contra.remove(user)

    fila_1v1.append(user)
    await atualizar_painel_principal(interaction.client)
    await interaction.response.defer()

    if len(fila_1v1) >= 2:
      p1 = fila_1v1.pop(0)
      p2 = fila_1v1.pop(0)
      await atualizar_painel_principal(interaction.client)
      await criar_sala_partida(interaction.guild, p1, p2, "1v1")

  @discord.ui.button(
      label="Entrar Pula Contra",
      style=discord.ButtonStyle.success,
      custom_id="btn_pula_contra",
  )
  async def callback_pula_contra(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user = interaction.user
    if user in fila_pula_contra:
      await interaction.response.defer()
      return

    if user in fila_1v1:
      fila_1v1.remove(user)

    fila_pula_contra.append(user)
    await atualizar_painel_principal(interaction.client)
    await interaction.response.defer()

    if len(fila_pula_contra) >= 2:
      p1 = fila_pula_contra.pop(0)
      p2 = fila_pula_contra.pop(0)
      await atualizar_painel_principal(interaction.client)
      await criar_sala_partida(interaction.guild, p1, p2, "Pula Contra")

  @discord.ui.button(
      label="Sair da Fila",
      style=discord.ButtonStyle.danger,
      custom_id="btn_sair_geral",
  )
  async def callback_sair_geral(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    user = interaction.user
    saiu = False

    if user in fila_1v1:
      fila_1v1.remove(user)
      saiu = True

    if user in fila_pula_contra:
      fila_pula_contra.remove(user)
      saiu = True

    if saiu:
      await atualizar_painel_principal(interaction.client)
    
    await interaction.response.defer()

  @discord.ui.button(
      label="Ranking Completo",
      style=discord.ButtonStyle.secondary,
      custom_id="btn_ranking_geral",
  )
  async def callback_ranking(
      self, interaction: discord.Interaction, button: discord.ui.Button
  ):
    if not ranking_vitorias and not ranking_derrotas:
      await interaction.response.send_message(
          "O ranking ainda está vazio!", ephemeral=True
      )
      return

    todos_membros = set(list(ranking_vitorias.keys()) + list(ranking_derrotas.keys()))
    texto = "🏆 **Ranking Geral Completo**\n\n"
    for uid in todos_membros:
      v = ranking_vitorias.get(uid, 0)
      d = ranking_derrotas.get(uid, 0)
      texto += f"• <@{uid}> — **{v}** Vitórias | **{d}** Derrotas\n"

    await interaction.response.send_message(texto, ephemeral=True)


class FilaDuplaView(discord.ui.View):
  """Painel 2: Inscrição de Capitães para o Evento de Duplas / Sorteio"""
  def __init__(self):
    super().__init__(timeout=None)

  def gerar_embed_duplas(self):
    embed = discord.Embed(
        title="🏆 Inscrição - Torneio de Duplas (Capitães)",
        description=(
            "Clique nos botões abaixo para gerenciar sua inscrição.\n"
            "⚠️ **Apenas o capitão/representante** deve se inscrever.\n\n"
            "**Capitães Inscritos:**"
        ),
        color=discord.Color.dark_gold(),
    )

    if not fila_duplas_inscritos:
      texto_inscritos = "Nenhum capitão inscrito ainda."
    else:
      texto_inscritos = "\n".join([f"{i+1}. {m.mention}" for i, m in enumerate(fila_duplas_inscritos)])

    embed.add_field(name=f"Total Inscritos: ({len(fila_duplas_inscritos)})", value=texto_inscritos, inline=False)
    return embed

  @discord.ui.button(
      label="Entrar na Fila",
      style=discord.ButtonStyle.primary,
      custom_id="btn_entrar_fila_dupla",
  )
  async def entrar_fila_dupla(self, interaction: discord.Interaction, button: discord.ui.Button):
    user = interaction.user
    if user in fila_duplas_inscritos:
      await interaction.response.send_message("Você já está inscrito na fila de duplas!", ephemeral=True)
      return

    fila_duplas_inscritos.append(user)
    await atualizar_painel_duplas(interaction.client)
    await interaction.response.send_message("Inscrição realizada com sucesso! Seu @ foi adicionado ao painel.", ephemeral=True)

  @discord.ui.button(
      label="Sair da Fila",
      style=discord.ButtonStyle.danger,
      custom_id="btn_sair_fila_dupla",
  )
  async def sair_fila_dupla(self, interaction: discord.Interaction, button: discord.ui.Button):
    user = interaction.user
    if user not in fila_duplas_inscritos:
      await interaction.response.send_message("Você não está inscrito nesta fila.", ephemeral=True)
      return

    fila_duplas_inscritos.remove(user)
    await atualizar_painel_duplas(interaction.client)
    await interaction.response.send_message("Você saiu da lista de capitães inscritos.", ephemeral=True)

  @discord.ui.button(
      label="🎲 Realizar Sorteio de Confrontos",
      style=discord.ButtonStyle.success,
      custom_id="btn_sorteio_duplas",
  )
  async def callback_sorteio(self, interaction: discord.Interaction, button: discord.ui.Button):
    if not interaction.user.guild_permissions.administrator:
      await interaction.response.send_message("Apenas administradores podem iniciar o sorteio.", ephemeral=True)
      return

    if len(fila_duplas_inscritos) < 2:
      await interaction.response.send_message("É necessário ter pelo menos 2 capitães inscritos para sortear confrontos.", ephemeral=True)
      return

    lista_sorteio = fila_duplas_inscritos.copy()
    random.shuffle(lista_sorteio)
    
    confrontos = []
    while len(lista_sorteio) >= 2:
      c1 = lista_sorteio.pop(0)
      c2 = lista_sorteio.pop(0)
      confrontos.append(f"⚔️ {c1.mention} **VS** {c2.mention}")
    
    sobra = ""
    if lista_sorteio:
      sobra = f"\n\n*⚠️ Observação: {lista_sorteio.mention} ficou sem par e passou de fase direto (W.O ou Bye).* "

    embed_resultado = discord.Embed(
        title="🎲 Confrontos Sorteados!",
        description="\n".join(confrontos) + sobra,
        color=discord.Color.gold()
    )
    await interaction.response.send_message(embed=embed_resultado)


# --- FUNÇÕES AUXILIARES DE ATUALIZAÇÃO ---
async def atualizar_painel_principal(client):
    pass

async def atualizar_painel_duplas(client):
    pass

async def criar_sala_partida(guild, p1, p2, modo):
    pass


# Inicialização das rotas do Flask em paralelo
keep_alive()

# Inicia o bot com o novo token do aplicativo configurado
bot.run('MTU1MDYxODYyNDM4Mzc4MzAzMw.GQeidh.j8IbO9hiv4TrE5j48dedIFbiL-tRPNpvmDX_FY')
