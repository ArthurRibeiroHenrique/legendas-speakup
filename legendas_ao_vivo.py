"""
Legendas ao vivo: inglês (fala) -> inglês + português na tela.
Usa o Azure AI Speech (plano Free F0).

Teclas:
  Esc  = sair
  F11  = alternar tela cheia
  P    = pausar / retomar
  + -  = aumentar / diminuir a fonte
  [ ]  = menos / mais palavras por tela
  L    = mostrar / esconder a frase anterior
"""

import os
import queue
import re
import sys
import tkinter as tk

import azure.cognitiveservices.speech as speechsdk

# Carrega o arquivo .env (se existir) da mesma pasta do script
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))
except ImportError:
    pass

# ---------------------------------------------------------------
# Configuração (lida das variáveis de ambiente)
# ---------------------------------------------------------------
KEY = os.environ.get("AZURE_SPEECH_KEY")
REGION = os.environ.get("AZURE_SPEECH_REGION")

IDIOMA_FALA = "en-US"   # idioma de quem fala
IDIOMA_ALVO = "pt"      # "pt" = português do Brasil

# Quantidade máxima de palavras mostradas por vez em cada idioma.
# Diminua para ter menos texto na tela (ajustável com [ e ]).
MAX_PALAVRAS = 14

# Silêncio (ms) que a Azure espera para "fechar" uma frase.
# Valores menores = frases mais curtas e trocas mais rápidas.
SILENCIO_MS = 500

# Cores do tema
COR_FUNDO = "#0d1022"
COR_CARTAO = "#161a36"
COR_BORDA = "#2b3166"
COR_DESTAQUE = "#7c6cff"
COR_TEXTO_DIM = "#6b7099"
COR_EN = "#ffffff"
COR_EN_ANT = "#7d84b3"
COR_PT = "#ffd34d"
COR_PT_ANT = "#9c8a4a"
COR_OUVINDO = "#3ddc84"
COR_PAUSADO = "#f0a030"
COR_ERRO = "#ff5c5c"
FONTE = "Segoe UI" if sys.platform == "win32" else "Helvetica"

if not KEY or not REGION:
    sys.exit(
        "Defina AZURE_SPEECH_KEY e AZURE_SPEECH_REGION antes de rodar.\n"
        "Veja o passo a passo."
    )

# Fila para passar textos das threads do SDK para a interface
fila = queue.Queue()


# ---------------------------------------------------------------
# Reconhecimento + tradução
# ---------------------------------------------------------------
def criar_reconhecedor():
    config = speechsdk.translation.SpeechTranslationConfig(
        subscription=KEY, region=REGION
    )
    config.speech_recognition_language = IDIOMA_FALA
    config.add_target_language(IDIOMA_ALVO)
    config.set_property(
        speechsdk.PropertyId.Speech_SegmentationSilenceTimeoutMs, str(SILENCIO_MS)
    )

    audio = speechsdk.audio.AudioConfig(use_default_microphone=True)
    rec = speechsdk.translation.TranslationRecognizer(
        translation_config=config, audio_config=audio
    )

    def parcial(evt):
        r = evt.result
        fila.put(("parcial", r.text, r.translations.get(IDIOMA_ALVO, "")))

    def final(evt):
        r = evt.result
        if r.reason == speechsdk.ResultReason.TranslatedSpeech and r.text:
            fila.put(("final", r.text, r.translations.get(IDIOMA_ALVO, "")))

    def cancelado(evt):
        detalhes = getattr(evt, "error_details", "") or str(evt.reason)
        fila.put(("erro", "Erro na conexão com a Azure", detalhes))

    rec.recognizing.connect(parcial)
    rec.recognized.connect(final)
    rec.canceled.connect(cancelado)
    return rec


# ---------------------------------------------------------------
# Corte do texto: mostra só o "pedaço" mais recente
# ---------------------------------------------------------------
def trecho_atual(texto, max_palavras):
    """Devolve apenas o final do texto, com no máximo `max_palavras`.

    1. Se o texto tem várias frases, fica só com as últimas que cabem.
    2. Se a última frase sozinha já é longa, divide em blocos fixos de
       `max_palavras` e mostra o último bloco (como "virar a página"),
       evitando que o texto fique deslizando palavra por palavra.
    """
    texto = (texto or "").strip()
    if not texto:
        return ""

    frases = [f for f in re.split(r"(?<=[.!?…])\s+", texto) if f]
    escolhidas = []
    total = 0
    for frase in reversed(frases):
        n = len(frase.split())
        if escolhidas and total + n > max_palavras:
            break
        escolhidas.insert(0, frase)
        total += n

    palavras = " ".join(escolhidas).split()
    if len(palavras) <= max_palavras:
        return " ".join(palavras)

    inicio = ((len(palavras) - 1) // max_palavras) * max_palavras
    bloco = palavras[inicio:]
    return ("… " if inicio > 0 else "") + " ".join(bloco)


# ---------------------------------------------------------------
# Interface
# ---------------------------------------------------------------
class Legendas:
    def __init__(self, root):
        self.root = root
        self.tamanho = 40
        self.max_palavras = MAX_PALAVRAS
        self.mostrar_anterior = True
        self.pausado = False
        self.erro = False
        self.pulso = False
        self.ult_en = ""
        self.ult_pt = ""
        self.atual_en = ""
        self.atual_pt = ""
        self.final_pendente = False

        root.title("Legendas ao vivo")
        root.configure(bg=COR_FUNDO)
        root.attributes("-fullscreen", True)

        self._montar_cabecalho()
        self._montar_rodape()

        # Área central com os dois cartões (EN e PT)
        centro = tk.Frame(root, bg=COR_FUNDO)
        centro.pack(expand=True, fill="both", padx=60)
        meio = tk.Frame(centro, bg=COR_FUNDO)
        meio.place(relx=0.5, rely=0.5, anchor="center", relwidth=1)

        self.en_ant, self.en = self._cartao(
            meio, "ENGLISH", "#3b82f6", "white", COR_EN_ANT, COR_EN)
        tk.Frame(meio, height=24, bg=COR_FUNDO).pack()
        self.pt_ant, self.pt = self._cartao(
            meio, "PORTUGUÊS", COR_PT, "#1a1a1a", COR_PT_ANT, COR_PT)

        self._aplicar_fontes()

        root.bind("<Escape>", lambda e: self.sair())
        root.bind("<F11>", lambda e: root.attributes(
            "-fullscreen", not root.attributes("-fullscreen")))
        root.bind("<p>", lambda e: self.pausar())
        root.bind("<P>", lambda e: self.pausar())
        root.bind("<plus>", lambda e: self.fonte(+4))
        root.bind("<equal>", lambda e: self.fonte(+4))
        root.bind("<minus>", lambda e: self.fonte(-4))
        root.bind("<bracketleft>", lambda e: self.palavras(-2))
        root.bind("<bracketright>", lambda e: self.palavras(+2))
        root.bind("<l>", lambda e: self.alternar_anterior())
        root.bind("<L>", lambda e: self.alternar_anterior())
        root.bind("<Configure>", self._ajustar_quebra)
        root.protocol("WM_DELETE_WINDOW", self.sair)

        self.rec = criar_reconhecedor()
        self.rec.start_continuous_recognition_async()
        self._verificar_fila()
        self._pulsar()

    # ---------- construção da tela ----------
    def _montar_cabecalho(self):
        topo = tk.Frame(self.root, bg=COR_FUNDO)
        topo.pack(fill="x", padx=40, pady=(24, 0))

        tk.Label(topo, text="SpeakUp", fg=COR_DESTAQUE, bg=COR_FUNDO,
                 font=(FONTE, 22, "bold")).pack(side="left")
        tk.Label(topo, text="  ·  Legendas ao vivo", fg=COR_TEXTO_DIM,
                 bg=COR_FUNDO, font=(FONTE, 16)).pack(side="left", pady=(4, 0))

        self.status = tk.Label(topo, text="Ouvindo", fg=COR_OUVINDO,
                               bg=COR_FUNDO, font=(FONTE, 14, "bold"))
        self.status.pack(side="right")
        self.ponto = tk.Canvas(topo, width=18, height=18, bg=COR_FUNDO,
                               highlightthickness=0)
        self.ponto.pack(side="right", padx=(0, 8))
        self.circulo = self.ponto.create_oval(3, 3, 15, 15, fill=COR_OUVINDO,
                                              outline="")

        # Linha de destaque em degradê
        faixa = tk.Canvas(self.root, height=3, bg=COR_FUNDO,
                          highlightthickness=0)
        faixa.pack(fill="x", padx=40, pady=(14, 0))
        faixa.bind("<Configure>", lambda e: self._degrade(faixa, e.width))

    def _degrade(self, canvas, largura):
        canvas.delete("all")
        ini = (0x3b, 0x82, 0xf6)   # azul
        fim = (0xff, 0xd3, 0x4d)   # amarelo
        passos = 60
        for i in range(passos):
            t = i / (passos - 1)
            cor = "#%02x%02x%02x" % tuple(
                int(a + (b - a) * t) for a, b in zip(ini, fim))
            x0 = largura * i / passos
            x1 = largura * (i + 1) / passos + 1
            canvas.create_rectangle(x0, 0, x1, 3, fill=cor, outline="")

    def _montar_rodape(self):
        self.rodape = tk.Label(self.root, text="", fg=COR_TEXTO_DIM,
                               bg=COR_FUNDO, font=(FONTE, 11))
        self.rodape.pack(side="bottom", pady=(0, 18))
        self._atualizar_rodape()

    def _atualizar_rodape(self):
        self.rodape.config(text=(
            "Esc sair   ·   F11 tela cheia   ·   P pausar   ·   + − fonte   ·   "
            f"[ ] palavras ({self.max_palavras})   ·   L frase anterior"
        ))

    def _cartao(self, pai, titulo, cor_selo, cor_texto_selo, cor_ant, cor_atual):
        borda = tk.Frame(pai, bg=COR_BORDA)
        borda.pack(fill="x")
        cartao = tk.Frame(borda, bg=COR_CARTAO)
        cartao.pack(fill="x", padx=1, pady=1)

        # barra lateral colorida
        tk.Frame(cartao, bg=cor_selo, width=6).pack(side="left", fill="y")

        corpo = tk.Frame(cartao, bg=COR_CARTAO)
        corpo.pack(side="left", fill="both", expand=True, padx=28, pady=20)

        tk.Label(corpo, text=f" {titulo} ", fg=cor_texto_selo, bg=cor_selo,
                 font=(FONTE, 10, "bold")).pack(anchor="w", pady=(0, 10))

        ant = tk.Label(corpo, text="", fg=cor_ant, bg=COR_CARTAO,
                       justify="center", wraplength=1200)
        ant.pack(fill="x")
        atual = tk.Label(corpo, text="", fg=cor_atual, bg=COR_CARTAO,
                         justify="center", wraplength=1200)
        atual.pack(fill="x", pady=(4, 0))
        return ant, atual

    def _aplicar_fontes(self):
        menor = max(int(self.tamanho * 0.5), 12)
        self.en_ant.config(font=(FONTE, menor))
        self.pt_ant.config(font=(FONTE, menor))
        self.en.config(font=(FONTE, self.tamanho, "bold"))
        self.pt.config(font=(FONTE, self.tamanho, "bold"))

    def _ajustar_quebra(self, _evt=None):
        largura = max(self.root.winfo_width() - 240, 300)
        for lbl in (self.en_ant, self.en, self.pt_ant, self.pt):
            lbl.config(wraplength=largura)

    # ---------- animação do indicador ----------
    def _pulsar(self):
        if self.erro:
            cor = COR_ERRO
        elif self.pausado:
            cor = COR_PAUSADO
        else:
            self.pulso = not self.pulso
            cor = COR_OUVINDO if self.pulso else "#1f6e45"
        self.ponto.itemconfig(self.circulo, fill=cor)
        self.root.after(600, self._pulsar)

    # ---------- ações das teclas ----------
    def fonte(self, delta):
        self.tamanho = min(max(self.tamanho + delta, 16), 96)
        self._aplicar_fontes()

    def palavras(self, delta):
        self.max_palavras = min(max(self.max_palavras + delta, 4), 40)
        self._atualizar_rodape()
        self._redesenhar()

    def alternar_anterior(self):
        self.mostrar_anterior = not self.mostrar_anterior
        self._redesenhar()

    def pausar(self):
        if self.pausado:
            self.rec.start_continuous_recognition_async()
            self.status.config(text="Ouvindo", fg=COR_OUVINDO)
        else:
            self.rec.stop_continuous_recognition_async()
            self.status.config(text="Pausado (aperte P)", fg=COR_PAUSADO)
        self.pausado = not self.pausado

    # ---------- atualização do texto ----------
    def _redesenhar(self):
        n = self.max_palavras
        self.en.config(text=trecho_atual(self.atual_en, n))
        self.pt.config(text=trecho_atual(self.atual_pt, n))
        if self.mostrar_anterior:
            # a frase anterior aparece mais curta, só como contexto
            n_ant = max(n // 2, 4)
            self.en_ant.config(text=trecho_atual(self.ult_en, n_ant))
            self.pt_ant.config(text=trecho_atual(self.ult_pt, n_ant))
        else:
            self.en_ant.config(text="")
            self.pt_ant.config(text="")

    def _verificar_fila(self):
        try:
            while True:
                tipo, en, pt = fila.get_nowait()
                if tipo == "parcial":
                    # começou uma frase nova: a que terminou vira "anterior"
                    if self.final_pendente:
                        self.ult_en, self.ult_pt = self.atual_en, self.atual_pt
                        self.final_pendente = False
                    self.atual_en, self.atual_pt = en, pt
                    self._redesenhar()
                elif tipo == "final":
                    self.atual_en, self.atual_pt = en, pt
                    self.final_pendente = True
                    self._redesenhar()
                elif tipo == "erro":
                    self.erro = True
                    self.status.config(text=f"{en}: {pt}", fg=COR_ERRO)
        except queue.Empty:
            pass
        self.root.after(50, self._verificar_fila)

    def sair(self):
        try:
            self.rec.stop_continuous_recognition_async().get()
        except Exception:
            pass
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    Legendas(root)
    root.mainloop()
