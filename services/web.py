import json
import re
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree


class WebSearchService:

	def __init__(self):

		self.headers = {
			"User-Agent": "Mozilla/5.0 HamsiBot/1.0"
		}

	def search(self, query, limit=5, news=False):

		path = "news/search" if news else "search"
		url = f"https://www.bing.com/{path}?" + urllib.parse.urlencode(
			{
				"q": query,
				"format": "rss",
				"setlang": "tr-TR",
				"cc": "TR"
			}
		)
		request = urllib.request.Request(
			url,
			headers=self.headers
		)

		with urllib.request.urlopen(
			request,
			timeout=8
		) as response:
			body = response.read().decode(
				"utf-8",
				errors="ignore"
			)

		root = ElementTree.fromstring(body)
		results = []

		for item in root.findall("./channel/item"):
			results.append(
				{
					"title": self._clean_text(item.findtext("title", "")),
					"url": self._clean_url(item.findtext("link", "")),
					"snippet": self._clean_text(item.findtext("description", ""))
				}
			)

		return results[:limit]

	def _clean_text(self, text):

		return re.sub(
			r"\s+",
			" ",
			text
		).strip()

	def _clean_url(self, url):

		parsed = urllib.parse.urlparse(url)

		if "bing.com" in parsed.netloc and parsed.path.endswith("/news/apiclick.aspx"):
			query = urllib.parse.parse_qs(parsed.query)
			return query.get(
				"url",
				[url]
			)[0]

		return url

	def weather(self, city, day_index=0):

		try:
			return self._weather_wttr(
				city,
				day_index
			)

		except Exception as wttr_error:
			try:
				return self._weather_open_meteo(
					city,
					day_index
				)

			except Exception as open_meteo_error:
				raise RuntimeError(
					f"wttr.in failed: {wttr_error!r}; open-meteo failed: {open_meteo_error!r}"
				) from open_meteo_error

	def _open_json(self, url, timeout=12, attempts=2):

		last_error = None

		for attempt in range(attempts):
			try:
				request = urllib.request.Request(
					url,
					headers=self.headers
				)

				with urllib.request.urlopen(
					request,
					timeout=timeout
				) as response:
					return json.loads(
						response.read().decode("utf-8")
					)

			except Exception as exc:
				last_error = exc
				if attempt + 1 < attempts:
					time.sleep(0.4)

		raise last_error

	def _weather_wttr(self, city, day_index):

		url = f"https://wttr.in/{urllib.parse.quote(city)}?format=j1&lang=tr"
		data = self._open_json(url)

		current = data["current_condition"][0]
		forecast = data.get(
			"weather",
			[]
		)
		day = forecast[day_index] if len(forecast) > day_index else {}
		hourly = day.get(
			"hourly",
			[]
		)
		midday = hourly[len(hourly) // 2] if hourly else {}
		description = current.get(
			"lang_tr",
			[{}]
		)[0].get(
			"value",
			""
		)

		if day_index > 0 and midday:
			description = midday.get(
				"lang_tr",
				[{}]
			)[0].get(
				"value",
				""
			)

		return {
			"city": city,
			"source": "wttr.in",
			"date": day.get("date", "bugün"),
			"temperature": current.get("temp_C", ""),
			"feels_like": current.get("FeelsLikeC", ""),
			"min_temperature": day.get("mintempC", ""),
			"max_temperature": day.get("maxtempC", ""),
			"humidity": current.get("humidity", ""),
			"description": description
		}

	def _weather_open_meteo(self, city, day_index):

		geo_url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode(
			{
				"name": city,
				"count": 1,
				"language": "tr",
				"format": "json"
			}
		)
		geo = self._open_json(geo_url)
		locations = geo.get(
			"results",
			[]
		)

		if not locations:
			raise RuntimeError(
				f"city not found: {city}"
			)

		location = locations[0]
		forecast_url = "https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
			{
				"latitude": location["latitude"],
				"longitude": location["longitude"],
				"current": "temperature_2m,relative_humidity_2m,apparent_temperature,weather_code",
				"daily": "weather_code,temperature_2m_max,temperature_2m_min",
				"timezone": "auto",
				"forecast_days": 3
			}
		)
		forecast = self._open_json(forecast_url)
		current = forecast.get(
			"current",
			{}
		)
		daily = forecast.get(
			"daily",
			{}
		)
		index = min(
			day_index,
			len(daily.get("time", [""])) - 1
		)

		return {
			"city": location.get("name", city),
			"source": "Open-Meteo",
			"date": daily.get("time", ["bugün"])[index],
			"temperature": str(current.get("temperature_2m", "")),
			"feels_like": str(current.get("apparent_temperature", "")),
			"min_temperature": str(daily.get("temperature_2m_min", [""])[index]),
			"max_temperature": str(daily.get("temperature_2m_max", [""])[index]),
			"humidity": str(current.get("relative_humidity_2m", "")),
			"description": self._weather_code_description(
				daily.get("weather_code", [current.get("weather_code", "")])[index]
			)
		}

	def _weather_code_description(self, code):

		descriptions = {
			0: "Açık",
			1: "Genellikle açık",
			2: "Parçalı bulutlu",
			3: "Kapalı",
			45: "Sisli",
			48: "Kırağılı sis",
			51: "Hafif çisenti",
			53: "Çisenti",
			55: "Yoğun çisenti",
			61: "Hafif yağmur",
			63: "Yağmur",
			65: "Kuvvetli yağmur",
			71: "Hafif kar",
			73: "Kar",
			75: "Yoğun kar",
			80: "Hafif sağanak",
			81: "Sağanak",
			82: "Kuvvetli sağanak",
			95: "Gök gürültülü fırtına"
		}

		return descriptions.get(
			int(code),
			"Bilinmiyor"
		)