"""
Legendas ao vivo: inglês (fala) -> inglês + português na tela.
Usa o Azure AI Speech (plano Free F0).

Teclas:
  Esc  = sair
  F11  = alternar tela cheia
  P    = pausar / retomar
  + -  = aumentar / diminuir a fonte
"""

import os
import queue
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
# Interface
# ---------------------------------------------------------------
class Legendas:
    def __init__(self, root):
        self.root = root
        self.tamanho = 40
        self.pausado = False
        self.ult_en = ""
        self.ult_pt = ""

        root.title("Legendas ao vivo")
        root.configure(bg="black")
        root.attributes("-fullscreen", True)

        self.status = tk.Label(root, text="Ouvindo...", fg="#777",
                               bg="black", font=("Arial", 14))
        self.status.pack(anchor="ne", padx=20, pady=10)

        # Linha anterior (menor, cinza) + linha atual (grande)
        self.en_ant = self._label("#888")
        self.en = self._label("white")
        tk.Frame(root, height=2, bg="#333").pack(fill="x", padx=60, pady=20)
        self.pt_ant = self._label("#8a7a2a")
        self.pt = self._label("#FFD700")

        self._aplicar_fontes()

        root.bind("<Escape>", lambda e: self.sair())
        root.bind("<F11>", lambda e: root.attributes(
            "-fullscreen", not root.attributes("-fullscreen")))
        root.bind("<p>", lambda e: self.pausar())
        root.bind("<P>", lambda e: self.pausar())
        root.bind("<plus>", lambda e: self.fonte(+4))
        root.bind("<equal>", lambda e: self.fonte(+4))
        root.bind("<minus>", lambda e: self.fonte(-4))
        root.bind("<Configure>", self._ajustar_quebra)
        root.protocol("WM_DELETE_WINDOW", self.sair)

        self.rec = criar_reconhecedor()
        self.rec.start_continuous_recognition_async()
        self._verificar_fila()

    def _label(self, cor):
        lbl = tk.Label(self.root, text="", fg=cor, bg="black",
                       justify="center", wraplength=1200)
        lbl.pack(fill="x", padx=60)
        return lbl

    def _aplicar_fontes(self):
        menor = max(int(self.tamanho * 0.55), 12)
        self.en_ant.config(font=("Arial", menor))
        self.pt_ant.config(font=("Arial", menor))
        self.en.config(font=("Arial", self.tamanho, "bold"))
        self.pt.config(font=("Arial", self.tamanho, "bold"))

    def _ajustar_quebra(self, _evt=None):
        largura = max(self.root.winfo_width() - 120, 300)
        for lbl in (self.en_ant, self.en, self.pt_ant, self.pt):
            lbl.config(wraplength=largura)

    def fonte(self, delta):
        self.tamanho = min(max(self.tamanho + delta, 16), 96)
        self._aplicar_fontes()

    def pausar(self):
        if self.pausado:
            self.rec.start_continuous_recognition_async()
            self.status.config(text="Ouvindo...")
        else:
            self.rec.stop_continuous_recognition_async()
            self.status.config(text="PAUSADO (aperte P)")
        self.pausado = not self.pausado

    def _verificar_fila(self):
        try:
            while True:
                tipo, en, pt = fila.get_nowait()
                if tipo == "parcial":
                    self.en.config(text=en)
                    self.pt.config(text=pt)
                elif tipo == "final":
                    self.en.config(text=en)
                    self.pt.config(text=pt)
                    # guarda para virar a "linha anterior" na próxima frase
                    self.en_ant.config(text=self.ult_en)
                    self.pt_ant.config(text=self.ult_pt)
                    self.ult_en, self.ult_pt = en, pt
                elif tipo == "erro":
                    self.status.config(text=f"{en}: {pt}", fg="red")
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
