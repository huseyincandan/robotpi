import datetime
import json
import re

from openai import OpenAI

from config import ASSISTANT
from config import WEB
from services.web import WebSearchService


class AssistantService:

	def __init__(self):

		self.client = None
		self.web = WebSearchService()
		self.reset()

	def reset(self):

		self.messages = [
			{
				"role": "system",
				"content": self._system_prompt()
			}
		]

	def _system_prompt(self):

		today = datetime.date.today().strftime("%d.%m.%Y")

		return f"{ASSISTANT['SYSTEM_PROMPT']} Bugünün tarihi: {today}."

	def _get_client(self):

		if self.client is None:
			self.client = OpenAI()

		return self.client

	def ask(self, text):

		if not ASSISTANT["USE_HISTORY"]:
			messages = [
				self.messages[0],
				{
					"role": "user",
					"content": text
				}
			]

			response = self._get_client().chat.completions.create(
				model=ASSISTANT["MODEL"],
				messages=messages,
				temperature=ASSISTANT["TEMPERATURE"]
			)

			return response.choices[0].message.content.strip()

		self.messages.append(
			{
				"role": "user",
				"content": text
			}
		)

		response = self._get_client().chat.completions.create(
			model=ASSISTANT["MODEL"],
			messages=self.messages,
			temperature=ASSISTANT["TEMPERATURE"]
		)

		answer = response.choices[0].message.content.strip()

		self.messages.append(
			{
				"role": "assistant",
				"content": answer
			}
		)

		self.messages = self.messages[:1] + self.messages[-ASSISTANT["MAX_HISTORY_MESSAGES"]:]

		return answer

	def ask_with_web(self, text, query=None):

		query = query or text
		context = self._web_context(
			text,
			query
		)
		print(
			"WEB CONTEXT:",
			context,
			flush=True
		)

		response = self._get_client().chat.completions.create(
			model=ASSISTANT["MODEL"],
			messages=[
				{
					"role": "system",
					"content": (
						"Sen HamsiBot adında Türkçe konuşan bir robot asistansın. "
						"Kullanıcıya sadece verilen web bağlamına dayanarak cevap ver. "
						"Bağlamda cevap yoksa açıkça söyle, uydurma. "
						"Kısa, net ve konuşma dilinde yanıt ver."
					)
				},
				{
					"role": "user",
					"content": (
						f"Soru: {text}\n\n"
						f"Web bağlamı:\n{context}"
					)
				}
			],
			temperature=ASSISTANT["TEMPERATURE"]
		)

		answer = response.choices[0].message.content.strip()

		if ASSISTANT["USE_HISTORY"]:
			self.messages.append(
				{
					"role": "user",
					"content": text
				}
			)
			self.messages.append(
				{
					"role": "assistant",
					"content": answer
				}
			)
			self.messages = self.messages[:1] + self.messages[-ASSISTANT["MAX_HISTORY_MESSAGES"]:]

		return answer

	def _web_context(self, text, query):

		plan = self._web_plan(
			text,
			query
		)
		print(
			"WEB PLAN:",
			plan,
			flush=True
		)

		if plan["source"] == "weather":
			city = self._weather_city_from_text_or_default(
				text,
				plan
			)
			day_index = self._weather_day_index_from_plan(plan)

			try:
				weather = self.web.weather(
					city,
					day_index=day_index
				)
				if day_index > 0:
					return (
						f"Hava durumu kaynağı: {weather.get('source', 'bilinmiyor')}\n"
						f"Şehir: {weather['city']}\n"
						f"Tarih: {weather['date']}\n"
						f"Beklenen en düşük sıcaklık: {weather['min_temperature']} C\n"
						f"Beklenen en yüksek sıcaklık: {weather['max_temperature']} C\n"
						f"Beklenen durum: {weather['description']}"
					)

				return (
					f"Hava durumu kaynağı: {weather.get('source', 'bilinmiyor')}\n"
					f"Şehir: {weather['city']}\n"
					f"Tarih: {weather['date']}\n"
					f"Sıcaklık: {weather['temperature']} C\n"
					f"Hissedilen: {weather['feels_like']} C\n"
					f"Nem: %{weather['humidity']}\n"
					f"Durum: {weather['description']}"
				)

			except Exception as exc:
				return f"Hava durumu alınamadı: {exc!r}"

		try:
			query = plan.get("query") or query
			news = plan["source"] == "news"
			results = self.web.search(
				query,
				limit=WEB["SEARCH_RESULT_LIMIT"],
				news=news
			)

		except Exception as exc:
			return f"Web araması başarısız oldu: {exc!r}"

		if not results:
			return "Web aramasında kullanılabilir sonuç bulunamadı."

		lines = []

		for index, result in enumerate(results, start=1):
			lines.append(
				f"{index}. {result['title']}\nURL: {result['url']}\nÖzet: {result['snippet']}"
			)

		source = "Bing News RSS" if news else "Bing Web RSS"

		return f"Arama kaynağı: {source}\nSorgu: {query}\n\n" + "\n\n".join(lines)

	def _web_plan(self, text, query):

		try:
			response = self._get_client().chat.completions.create(
				model=WEB["PLAN_MODEL"],
				messages=[
					{
						"role": "system",
						"content": WEB["PLAN_SYSTEM_PROMPT"]
					},
					{
						"role": "user",
						"content": f"Soru: {text}\nÖn sorgu: {query}"
					}
				],
				temperature=0,
				response_format={"type": "json_object"}
			)
			plan = json.loads(
				response.choices[0].message.content
			)

		except Exception:
			plan = {}

		source = plan.get(
			"source",
			""
		)

		if source not in ["weather", "news", "web"]:
			if self._looks_like_weather(text):
				source = "weather"

			elif self._looks_like_current_event(text) or self._looks_like_current_event(query):
				source = "news"

			else:
				source = "web"

		return {
			"source": source,
			"query": plan.get("query") or query or text,
			"city": self._weather_city_from_plan_if_explicit(
				text,
				plan
			),
			"day": self._weather_day_from_text(text) or plan.get("day") or "today"
		}

	def _looks_like_weather(self, text):

		return any(
			word in text.lower()
			for word in [
				"hava",
				"sıcaklık",
				"yağmur",
				"kaç derece"
			]
		)

	def _looks_like_current_event(self, text):

		return any(
			word in text.lower()
			for word in [
				"haber",
				"son dakika",
				"toplantı",
				"zirve",
				"maç",
				"sonuç",
				"sonucu",
				"ne zaman",
				"bugün",
				"yarın"
			]
		)

	def _weather_city_from_text_or_default(
		self,
		text,
		plan
	):

		return (
			self._explicit_weather_city_from_text(text) or
			self._weather_city_from_plan_if_explicit(text, plan) or
			WEB["WEATHER_DEFAULT_CITY"]
		)

	def _weather_city_from_plan_if_explicit(
		self,
		text,
		plan
	):

		city = (
			plan.get("city") or ""
		).strip()

		if not city:
			return ""

		if city.lower() in text.lower():
			return city

		return ""

	def _explicit_weather_city_from_text(
		self,
		text
	):

		match = re.search(
			r"([A-ZÇĞİÖŞÜ][a-zçğıöşü]+)(?:'|’)?(?:da|de|ta|te)\b",
			text
		)

		if match:
			return match.group(1)

		return ""

	def _weather_day_index(self, text):

		day = self._weather_day_from_text(text)

		if day == "tomorrow":
			return 1

		if day == "day_after_tomorrow":
			return 2

		return 0

	def _weather_day_from_text(self, text):

		lower_text = text.lower()

		if "yarın" in lower_text:
			return "tomorrow"

		if "öbür gün" in lower_text or "öbürgün" in lower_text:
			return "day_after_tomorrow"

		return ""

	def _weather_day_index_from_plan(self, plan):

		day = plan.get(
			"day",
			"today"
		)

		if day == "tomorrow":
			return 1

		if day == "day_after_tomorrow":
			return 2

		return 0