"""Кнопка «Сказать»: запись голоса → текст → команда помощнику (как будто её набрали)."""
import threading
from tkinter import ttk

import iskra_addons
import iskra_voice as voice


class VoiceMixin:
    def voice_button(self, parent):
        self.voice_rec = None
        self.voice_btn = ttk.Button(parent, text='🎤 Сказать', command=self.voice_toggle)
        if not iskra_addons.installed('voice'):
            self.voice_btn.state(['disabled'])
        return self.voice_btn

    def voice_toggle(self):
        if not voice.available():
            self.say('Голосовые команды: нужен дополнительный архив Iskra-dop-golos.zip (распакуйте поверх Искры).', 'proof')
            return
        if self.voice_rec is None:
            rec = voice.Recorder()
            try:
                rec.start()
            except RuntimeError as exc:
                self.say('Микрофон: ' + str(exc)); return
            self.voice_rec = rec
            self.voice_btn.configure(text='■ Готово')
            self.status.set('Говорите… Нажмите «Готово», когда закончите (не дольше 30 секунд).')
            self.root.after(voice.MAX_SECONDS * 1000 + 500, lambda r=rec: self.voice_rec is r and self.voice_toggle())
            return
        rec, self.voice_rec = self.voice_rec, None
        self.voice_btn.configure(text='🎤 Сказать')
        self.status.set('Распознаю речь…')

        def work():
            try:
                wav = rec.stop()
                text = voice.transcribe(wav) if wav else ''
                if wav:
                    voice.cleanup(wav)
            except Exception as exc:
                msg = str(exc)
                self.events.put(('call', lambda: (self.status.set('Готов к работе'), self.say('Голос: ' + msg))))
                return

            def done():
                self.status.set('Готов к работе')
                if not text:
                    self.say('Не расслышала. Говорите ближе к микрофону и чуть медленнее.', 'proof'); return
                self.question.set(text)
                self.say(f'Вы сказали: «{text}»', 'proof')
                self.ask()
            self.events.put(('call', done))
        threading.Thread(target=work, daemon=True).start()
