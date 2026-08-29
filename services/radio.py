import json
import random
import urllib.parse
import urllib.request

from config import RADIO


class RadioDirectory:

	def __init__(self):

		self.headers = {
			"User-Agent": RADIO["USER_AGENT"]
		}

	def resolve_genre(self, query):

		normalized = (query or "").strip().lower()

		for genre in RADIO["GENRES"]:
			if any(keyword in normalized for keyword in genre["KEYWORDS"]):
				return genre

		return random.choice(RADIO["GENRES"])

	def find_stations(self, genre):

		params = dict(genre["PARAMS"])
		params.update(
			{
				"limit": RADIO["SEARCH_LIMIT"],
				"hidebroken": "true",
				"order": "clickcount",
				"reverse": "true"
			}
		)
		url = f"{RADIO['API_BASE']}/json/stations/search?" + urllib.parse.urlencode(params)
		request = urllib.request.Request(
			url,
			headers=self.headers
		)

		with urllib.request.urlopen(
			request,
			timeout=RADIO["REQUEST_TIMEOUT_SECONDS"]
		) as response:
			body = response.read().decode(
				"utf-8",
				errors="ignore"
			)

		entries = json.loads(body)
		stations = []

		for entry in entries:
			url_resolved = entry.get("url_resolved") or entry.get("url")

			if not url_resolved:
				continue

			stations.append(
				{
					"name": entry.get("name") or genre["LABEL"],
					"url": url_resolved
				}
			)

		return stations

	def list_genre_labels(self):

		return [genre["LABEL"] for genre in RADIO["GENRES"]]
