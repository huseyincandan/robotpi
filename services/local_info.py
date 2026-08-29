import datetime


class LocalInfoService:

	def answer(self, text):

		now = datetime.datetime.now()
		lower_text = text.lower()
		date_text = self._format_date(now)
		time_text = self._format_time(now)

		asks_time = any(
			word in lower_text
			for word in [
				"saat",
				"kaç"
			]
		)
		asks_date = any(
			word in lower_text
			for word in [
				"tarih",
				"bugün günlerden",
				"günlerden ne"
			]
		)

		if asks_time and asks_date:
			return f"Bugün {date_text}. Saat {time_text}."

		if asks_date:
			return f"Bugün {date_text}."

		return f"Saat {time_text}."

	def _format_time(self, now):

		return f"{self._number_to_words(now.hour)} {self._minute_to_words(now.minute)}".strip()

	def _minute_to_words(self, minute):

		if minute == 0:
			return ""

		if minute < 10:
			return f"sıfır {self._number_to_words(minute)}"

		return self._number_to_words(minute)

	def _number_to_words(self, number):

		ones = [
			"sıfır",
			"bir",
			"iki",
			"üç",
			"dört",
			"beş",
			"altı",
			"yedi",
			"sekiz",
			"dokuz"
		]
		tens = [
			"",
			"on",
			"yirmi",
			"otuz",
			"kırk",
			"elli"
		]

		if number < 10:
			return ones[number]

		if number < 20:
			if number == 10:
				return "on"

			return f"on {ones[number - 10]}"

		ten = number // 10
		one = number % 10

		if one == 0:
			return tens[ten]

		return f"{tens[ten]} {ones[one]}"

	def _format_date(self, now):

		months = [
			"Ocak",
			"Şubat",
			"Mart",
			"Nisan",
			"Mayıs",
			"Haziran",
			"Temmuz",
			"Ağustos",
			"Eylül",
			"Ekim",
			"Kasım",
			"Aralık"
		]
		weekdays = [
			"Pazartesi",
			"Salı",
			"Çarşamba",
			"Perşembe",
			"Cuma",
			"Cumartesi",
			"Pazar"
		]

		return f"{now.day} {months[now.month - 1]} {now.year}, {weekdays[now.weekday()]}"