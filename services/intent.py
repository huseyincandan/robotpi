import json
import re
import unicodedata

from services.llm import create_client, complete, INTENT_SCHEMA, INTENT_TYPES

from config import INTENT
from services.conversation_text import music_topic, needs_web


class IntentService:

	def __init__(self):

		self.client = None

	def _get_client(self):

		if self.client is None:
			self.client = create_client()

		return self.client

	def classify(self, text):

		local_intent = self._classify_local(text)

		if local_intent:
			return local_intent

		response = complete(
			self._get_client(),
			model=INTENT["MODEL"],
			messages=[
				{
					"role": "system",
					"content": INTENT["SYSTEM_PROMPT"]
				},
				{
					"role": "user",
					"content": text
				}
			],
			temperature=INTENT["TEMPERATURE"],
			schema=INTENT_SCHEMA
		)

		try:
			intent = json.loads(
				response.choices[0].message.content
			)

		except (json.JSONDecodeError, TypeError):
			return {
				"type": "chat",
				"query": ""
			}

		if not isinstance(intent, dict) or intent.get("type") not in INTENT_TYPES:
			return {"type": "chat", "query": ""}

		# Listing arbitrary things must not trigger the robot's music catalogue.
		if intent["type"] == "music.genres" and not music_topic(text):
			return {"type": "chat", "query": ""}
		# Ordinary knowledge questions can be answered without a web round trip.
		if intent["type"] == "web.search" and not needs_web(text):
			return {"type": "chat", "query": ""}

		return {
			"type": intent["type"],
			"query": intent.get("query", "") if isinstance(intent.get("query", ""), str) else ""
		}

	def _classify_local(self, text):

		normalized = unicodedata.normalize(
			"NFKD",
			text.lower()
		)
		normalized = "".join(
			character
			for character in normalized
			if not unicodedata.combining(character)
		)
		normalized = re.sub(
			r"\s+",
			" ",
			normalized
		).strip()

		if self._is_shutdown_command(normalized):
			return {
				"type": "system.shutdown",
				"query": ""
			}

		asks_time = "saat" in normalized
		asks_date = any(
			phrase in normalized
			for phrase in [
				"tarih",
				"bugün günlerden",
				"günlerden ne"
			]
		)

		if asks_time or asks_date:
			return {
				"type": "local.time",
				"query": ""
			}

		if self._is_weather_command(normalized):
			return {
				"type": "web.search",
				"query": text
			}

		if self._is_volume_command(normalized):
			return {
				"type": "audio.volume",
				"query": text
			}

		if self._is_device_status_command(normalized):
			return {
				"type": "device.status",
				"query": text
			}

		music_control = self._music_control_intent(normalized)

		if music_control:
			return music_control

		if self._is_move_command(normalized):
			return {
				"type": "robot.move",
				"query": text
			}

		if self._is_chat_command(normalized):
			return {
				"type": "chat",
				"query": ""
			}

		return None

	def _music_control_intent(self, normalized):

		if not any(
			word in normalized
			for word in ["muzik", "muzigi", "muzige", "müzigi", "müziği", "müziğe", "sarki", "sarkı", "sarkiyi", "sarkıyı", "şarkı", "şarkıyı", "parca", "parcayi", "parcayı", "parça", "parçayı", "kanal", "kanali", "kanalı", "radyo", "istasyon", "istasyonu"]
		):
			return None

		if any(word in normalized for word in ["durdur", "kapat", "kes"]):
			return {
				"type": "music.stop",
				"query": ""
			}

		if any(word in normalized for word in ["onceki", "önceki", "geri"]):
			return {
				"type": "music.previous",
				"query": ""
			}

		if any(word in normalized for word in ["sonraki", "siradaki", "sıradaki", "ileri", "degistir", "değiştir", "baska", "başka", "farkli", "farklı"]):
			return {
				"type": "music.next",
				"query": ""
			}

		if any(word in normalized for word in ["duraklat", "beklet", "pause"]):
			return {
				"type": "music.pause",
				"query": ""
			}

		if any(word in normalized for word in ["devam", "surdur", "sürdür", "oynat", "resume"]):
			return {
				"type": "music.resume",
				"query": ""
			}

		return None

	def _is_weather_command(self, normalized):

		if any(
			phrase in normalized
			for phrase in [
				"hava",
				"sicaklik",
				"sıcaklık",
				"yagmur",
				"yağmur",
				"kar yagacak",
				"kar yağacak",
				"kac derece",
				"kaç derece"
			]
		):
			return True

		has_day_reference = any(
			phrase in normalized
			for phrase in [
				"yarin",
				"yarın",
				"bugun",
				"bugün",
				"obur gun",
				"öbür gün",
				"hafta sonu",
				"sabah",
				"aksam",
				"akşam"
			]
		)

		has_outlook_question = any(
			phrase in normalized
			for phrase in [
				"nasil olacak",
				"nasıl olacak",
				"nasil gececek",
				"nasıl geçecek",
				"ne olacak"
			]
		)

		return has_day_reference and has_outlook_question

	def _is_chat_command(self, normalized):

		chat_phrases = [
			"fıkra",
			"fikra",
			"saka",
			"hikaye",
			"masal",
			"beni guldur",
			"nasil gidiyor",
			"nasilsin",
			"sohbet edelim"
		]

		return any(
			phrase in normalized
			for phrase in chat_phrases
		)

	def _is_shutdown_command(self, normalized):

		shutdown_phrases = [
			"kendini kapat",
			"robotu kapat",
			"hamsibot u kapat",
			"hamsibotu kapat",
			"pi yi kapat",
			"raspberry pi yi kapat",
			"sistemi kapat",
			"bilgisayarı kapat",
			"tamamen kapat"
		]

		return any(
			phrase in normalized
			for phrase in shutdown_phrases
		)

	def _is_volume_command(self, normalized):

		words = set(
			normalized.split()
		)

		if words.isdisjoint(
			[
				"ses",
				"sesi",
				"sesini",
				"volume",
				"hoparlor",
				"hoparlör"
			]
		):
			return False

		has_action_word = not words.isdisjoint(
			[
				"artır",
				"artir",
				"arttır",
				"arttir",
				"yükselt",
				"yukselt",
				"yuksel",
				"aç",
				"ac",
				"azalt",
				"kıs",
				"kis",
				"düşür",
				"dusur",
				"yap",
				"ayarla",
				"yuzde",
				"yüzde"
			]
		)

		has_query_phrase = any(
			phrase in normalized
			for phrase in [
				"kacta",
				"kaçta",
				"kac",
				"kaç",
				"nedir",
				"ne kadar",
				"ne durumda"
			]
		)

		return has_action_word or has_query_phrase

	def _is_device_status_command(self, normalized):

		return any(
			word in normalized
			for word in [
				"batarya",
				"pil",
				"sarj",
				"şarj",
				"akim",
				"akım",
				"amper",
				"voltaj",
				"gerilim",
				"guc",
				"güç"
			]
		)

	def _is_move_command(self, normalized):

		movement_words = [
			"gezin",
			"gezinsin",
			"gezsin",
			"dolaş",
			"dolas",
			"dolaşsın",
			"dolassin",
			"keşfet",
			"kesfet",
			"serbest",
			"ileri",
			"geri",
			"öne",
			"one",
			"arkaya",
			"sağa",
			"saga",
			"sola",
			"sağ",
			"sag",
			"sol",
			"dur",
			"fren"
		]
		verbs = [
			"gezin",
			"gezinsin",
			"gezsin",
			"dolaş",
			"dolas",
			"dolaşsın",
			"dolassin",
			"keşfet",
			"kesfet",
			"git",
			"gel",
			"dön",
			"don",
			"hareket",
			"ilerle",
			"dur",
			"durdur",
			"fren"
		]

		return (
			any(word in normalized for word in movement_words) and
			any(verb in normalized for verb in verbs)
		)
