"""Small shared helpers for Turkish intent and follow-up matching."""

import re
import unicodedata


def normalize(text):
    text = unicodedata.normalize("NFKD", text.lower().replace("ı", "i"))
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def music_topic(text):
    words = normalize(text).split()
    return any(word.startswith(("muzik", "radyo", "sarki", "kanal", "istasyon"))
               for word in words)


def generic_search_request(text):
    words = normalize(text).split()
    if not words:
        return False
    verbs = {"ara", "arastir", "arastirir", "arastirsana", "arastirabilir", "bak", "bul", "kontrol"}
    filler = {"internetten", "internette", "internet", "web", "webden", "webde", "bir", "de",
              "bunu", "sunu", "onu", "bu", "konuyu", "lutfen", "eder", "ederim", "et",
              "misin", "musun", "bana", "sen", "da", "daha", "ayrintili", "detayli"}
    return any(word in verbs for word in words) and all(word in verbs | filler for word in words)


def needs_web(text):
    text = normalize(text)
    return any(word in text for word in (
        "internet", "web", "arastir", "arama yap", "haber", "son dakika", "guncel",
        "bugun", "yarin", "hava durumu", "kac derece", "doviz", "borsa", "mac sonucu",
        "ne zaman", "son durum", "en son", "fiyat", "kac para", "resmi site",
    ))
