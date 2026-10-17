"""Bounded spoken identification/enrollment, independent of LLM tool routing."""
import asyncio
import re
import unicodedata

from config import STT
from services.speaker_identity import load_audio


def normalized(text):
    return unicodedata.normalize('NFC', text).lower().replace('i\u0307', 'i').replace('ı', 'i').strip(' .!?')


def is_cancel(text):
    text = ' '.join(normalized(text).split())
    return text in ('iptal', 'iptal et', 'iptal lütfen', 'lütfen iptal',
                    'kaydı iptal et', 'işlemi iptal et', 'vazgeç', 'vazgeçtim', 'ipter')


def parse_name(text):
    text = text.strip(' .!?')
    text = re.sub(r'^(benim adım|benim ismim|adım|ismim|ben)\s+', '', text, flags=re.I)
    text = re.sub(r'\s+(benim adım|benim ismim)$', '', text, flags=re.I)
    words = text.split()
    if not 1 <= len(words) <= 4 or any(not (c.isalpha() or c in " '-") for c in text):
        return None
    if is_cancel(text) or normalized(text) in ('hayir', 'bilmiyorum'):
        return None
    return ' '.join(words)


def profile_request(text):
    """Explicit first-person profile actions; leave questions/general chat alone."""
    text = normalized(text)
    if not re.search(r'\bses\s+profil', text):
        return None
    if re.search(r'\b(?:güncelleme|oluşturma|kaydetme)(?: lütfen)?$|istemiyorum|vazgeç', text):
        return None
    if re.search(r'güncelle(?:yelim|yebilir misin|meni istiyorum|mek istiyorum)?\b|yenile(?:yelim)?\b|yeniden (?:kaydet|oluştur)', text):
        return 'update'
    if re.search(r'oluştur(?:alim|alım|abilir misin|mani istiyorum|manı istiyorum|mak istiyorum)?\b|kaydet(?:mek istiyorum)?\b|ekle(?:yelim)?\b', text):
        return 'create'
    return None


class SpeakerDialog:
    def __init__(self, identity, stt, speech):
        self.identity, self.stt, self.speech = identity, stt, speech

    async def say(self, text):
        await asyncio.to_thread(self.speech.say_local, text)

    async def listen(self, prompt):
        await self.say(prompt)
        text = await asyncio.to_thread(self.stt.listen, self.speech.beep)
        if not text or is_cancel(text):
            return None, None
        try:
            audio = load_audio(STT['RECORD_FILE'])
        except (OSError, ValueError):
            return None, None
        return text, audio

    async def run(self, mode=None):
        self.identity.end_session()  # Discard any in-flight guess before explicit identification.
        callback = self.stt.on_recorded
        self.stt.on_recorded = None
        try:
            return await self._run(mode)
        except Exception as exc:
            print('SPEAKER DIALOG ERROR:', repr(exc), flush=True)
            await self.say('Ses profilini şu an doğrulayamadım. İsimsiz devam edebiliriz.')
            return None
        finally:
            self.stt.on_recorded = callback

    async def _run(self, mode=None):
        prompt = ('Ses profilini güncellemek için adın ne? İstersen iptal diyebilirsin.' if mode == 'update'
                  else 'Ses profilini oluşturmak için adın ne? İstersen iptal diyebilirsin.' if mode == 'create'
                  else 'Sesinden seni tanıyamadım. Adın ne? İstersen iptal diyebilirsin.')
        while True:
            text, _ = await self.listen(prompt)
            if not text:
                await self.say('Profil oluşturmadan devam ediyorum.')
                return None
            name = parse_name(text)
            if not name:
                prompt = 'Adını anlayamadım. Tekrar söyler misin? İptal diyerek çıkabilirsin.'
                continue
            text, _ = await self.listen(f'Adını {name} olarak duydum. Doğru mu? Evet veya hayır diyebilirsin.')
            if not text:
                await self.say('İsmi kaydetmedim. Profil oluşturmadan devam ediyorum.')
                return None
            if normalized(text) in ('evet', 'evet doğru', 'doğru', 'evet dogru', 'dogru'):
                break
            prompt = 'O zaman adını tekrar söyler misin? İptal diyerek çıkabilirsin.'
        existing = self.identity.profile_named(name)
        if existing:
            text, audio = await self.listen('Bu isimde kayıtlı bir profil var. Yeniden kontrol etmek için şunu söyle: Bugün seninle biraz sohbet etmek istiyorum.')
            if audio is not None and await asyncio.to_thread(self.identity.verify_claim, name, audio):
                if mode == 'update':
                    text, _ = await self.listen('Sesini doğruladım. Yeni örneklerle mevcut ses profilini güncelleyeyim mi?')
                    if not text or normalized(text) != 'evet':
                        await self.say('Eski ses profilini korudum.')
                        return existing['name']
                    return await self.collect(existing['name'], update=True)
                await self.say(f'Seni tanıdım {existing["name"]}.')
                return existing['name']
            if mode == 'update':
                await self.say('Sesini mevcut profille doğrulayamadım. Eski profilini korudum.')
                return None
            text, _ = await self.listen('Sesin bu profille eşleşmedi. Bu robota ilk kez mi ses profili kaydettiriyorsun? Evet veya hayır diyebilirsin.')
            if not text or normalized(text) not in ('evet', 'evet ilk kez', 'ilk kez'):
                await self.say('Mevcut profilini değiştirmedim. İsimsiz devam edebiliriz.')
                return None
            text, _ = await self.listen('Mevcut profilden ayırabilmem için soyadınla birlikte farklı bir kayıt adı söyler misin?')
            name = parse_name(text) if text else None
            if not name or self.identity.profile_named(name):
                await self.say('Ayrı bir kayıt adı belirleyemedim. Profil oluşturmadan devam ediyorum.')
                return None
            text, _ = await self.listen(f'Yeni ses profilini {name} adıyla kaydedeyim mi?')
            if not text or normalized(text) != 'evet':
                return None
        else:
            text, _ = await self.listen(f'{name}, kayıtlı profilin yok. Birkaç cümleyle ses profilini kaydedeyim mi?')
            if not text or normalized(text) != 'evet':
                await self.say('Profil oluşturmadan devam ediyorum.')
                return None
        return await self.collect(name)

    async def collect(self, name, update=False):
        wake, command = [], []
        prompts = [('wake', 'Hey Jarvis'), ('wake', 'Hey Jarvis'), ('wake', 'Hey Jarvis'),
                   ('command', 'Bugün seninle biraz sohbet etmek istiyorum'),
                   ('command', 'Yarın hava güzel olursa dışarıda yürüyüş yapacağım'),
                   ('command', 'En sevdiğim müzikleri dinlemek bana iyi geliyor')]
        await self.say('Şimdi söyleyeceğim ifadeleri bipten sonra tekrarla. İptal diyerek çıkabilirsin.')
        for phase, phrase in prompts:
            accepted = None
            for _ in range(2):
                text, audio = await self.listen(f'Lütfen tekrarla: {phrase}.')
                if audio is None:
                    await self.say('Kayıt tamamlanmadı. Profil kaydetmedim.')
                    return None
                accepted = await asyncio.to_thread(self.identity.prepare_sample, audio, phase)
                if accepted is not None:
                    break
                await self.say('Yeterince net ve uzun ses alamadım. Bir kez daha deneyelim.')
            if accepted is None:
                await self.say('Yeterli ses alamadım. Profil kaydetmedim.')
                return None
            (wake if phase == 'wake' else command).append(accepted)
        if update:
            await asyncio.to_thread(self.identity.enroll_samples, name, wake, command, update=True)
            await self.say(f'Ses profilini güncelledim {name}.')
            return name
        await asyncio.to_thread(self.identity.enroll_samples, name, wake, command)
        await self.say(f'Ses profilini kaydettim {name}. Sonraki gelişinde seni tanımayı deneyeceğim.')
        return name
