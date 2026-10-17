import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from services.assistant import AssistantService
from services.conversation_text import generic_search_request
from services.intent import IntentService
from services.web import WebSearchService, BraveResultParser


def response(value):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=value))])


class ConversationRegressionTests(unittest.TestCase):
    def setUp(self):
        for module in ("services.intent", "services.assistant"):
            client_patch = patch(module + ".create_client", return_value=MagicMock())
            client_patch.start()
            self.addCleanup(client_patch.stop)

    def test_university_listing_does_not_trigger_music_catalogue(self):
        service = IntentService()
        for text in ["Bildiğin üniversite bölümlerini say bana.", "Bildiğin üniversite bölümlerine say."]:
            with self.subTest(text=text):
                with patch.object(service, "_classify_local", return_value=None):
                    with patch("services.intent.complete", return_value=response(json.dumps({"type": "music.genres", "query": ""}))):
                        self.assertEqual(service.classify(text)["type"], "chat")

    def test_actual_radio_catalogue_request_is_preserved(self):
        service = IntentService()
        with patch("services.intent.complete", return_value=response('{"type":"music.genres","query":""}')):
            self.assertEqual(service.classify("Hangi radyo türleri var?")["type"], "music.genres")

    def test_general_knowledge_does_not_force_web_but_explicit_search_does(self):
        service = IntentService()
        with patch("services.intent.complete", return_value=response('{"type":"web.search","query":"üniversite bölümleri"}')):
            self.assertEqual(service.classify("Üniversitelerde hangi bölümler var?")["type"], "chat")
            self.assertEqual(service.classify("Üniversite bölümlerini internetten araştır.")["type"], "web.search")

    def test_search_followup_preserves_previous_subject(self):
        assistant = AssistantService()
        assistant.messages.extend([
            {"role": "user", "content": "Üniversitelerde hangi bölümler var?"},
            {"role": "assistant", "content": "Tıp, hukuk ve mühendislik gibi bölümler var."},
        ])
        with patch.object(assistant, "_web_context", return_value="Konuyla ilgili sonuç yok") as context:
            with patch("services.assistant.complete", return_value=response("Güvenilir sonuç bulamadım.")):
                assistant.ask_with_web("İnternetten araştır.", "")
        context.assert_called_once_with("Üniversitelerde hangi bölümler var?", "Üniversitelerde hangi bölümler var?")

    def test_search_without_prior_subject_asks_for_topic(self):
        assistant = AssistantService()
        with patch.object(assistant, "_web_context") as context:
            self.assertIn("hangi konuyu", assistant.ask_with_web("İnternetten araştır."))
            context.assert_not_called()

    def test_new_explicit_subject_is_not_replaced_with_old_one(self):
        self.assertFalse(generic_search_request("İnternetten ODTÜ bölümlerini araştır."))
        self.assertTrue(generic_search_request("Bunu internetten araştırır mısın?"))

    def test_generic_offer_is_removed_but_specific_followup_question_is_kept(self):
        assistant = AssistantService()
        self.assertEqual(assistant._clean_answer("Tıp ve hukuk gibi bölümler var. Başka bir konuda yardımcı olabilir miyim?"),
                         "Tıp ve hukuk gibi bölümler var.")
        specific = "Tıp ve hukuk gibi bölümler var. Hangi alan ilgini çekiyor?"
        self.assertEqual(assistant._clean_answer(specific), specific)
        self.assertEqual(assistant._clean_answer("Anladım, başka bir konuda yardımcı olabilir miyim?"), "Anladım.")

    def test_unrelated_windows_results_are_rejected_for_university_query(self):
        search = WebSearchService()
        self.assertFalse(search._relevant("Orta Doğu Teknik Üniversitesi bölümleri", {
            "title": "Windows Güvenliği uygulaması", "snippet": "Bilgisayarınızı koruyun", "url": "https://support.microsoft.com"
        }))
        self.assertTrue(search._relevant("Orta Doğu Teknik Üniversitesi bölümleri", {
            "title": "Orta Doğu Teknik Üniversitesi: Lisans programları", "snippet": "Mühendislik fakültesi", "url": "https://www.metu.edu.tr"
        }))

    def test_only_relevant_results_reach_the_assistant(self):
        search = WebSearchService()
        rss = b'<rss><channel><item><title>Windows Defender</title><link>https://microsoft.com</link><description>Virus protection</description></item></channel></rss>'
        result = MagicMock()
        result.__enter__.return_value.read.return_value = rss
        with patch("services.web.urllib.request.urlopen", return_value=result):
            self.assertEqual(search.search("universite bolumleri"), [])

    def test_fallback_parser_extracts_result_title_url_and_nested_snippet(self):
        parser = BraveResultParser()
        parser.feed('<div class="snippet extra" data-type="web">'
                    '<div><a class="l1 other" href="https://www.metu.edu.tr/tr/lisans-programlari">'
                    '<div class="search-snippet-title" title="ODTÜ Lisans Programları">ODTÜ</div></a>'
                    '<div class="generic-snippet"><div>Fizik ve <b>Kimya</b></div></div>'
                    '</div></div>')
        self.assertEqual(parser.results, [{"title": "ODTÜ Lisans Programları",
            "url": "https://www.metu.edu.tr/tr/lisans-programlari",
            "snippet": "Fizik ve Kimya", "source": "Brave Search"}])

    def test_empty_primary_search_uses_alternate_provider(self):
        search = WebSearchService()
        page = ('<div class="snippet" data-type="web"><a class="l1" href="https://www.metu.edu.tr">'
                '<div class="search-snippet-title" title="ODTÜ lisans programları">ODTÜ</div></a>'
                '<div class="generic-snippet">Fizik ve Kimya</div></div>').encode()
        alternate = MagicMock()
        alternate.__enter__.return_value.read.return_value = page
        with patch.object(search, "_search_bing", return_value=[]):
            with patch("services.web.urllib.request.urlopen", return_value=alternate):
                results = search.search("ODTÜ lisans programları")
        self.assertEqual(results[0]["source"], "Brave Search")


if __name__ == "__main__":
    unittest.main()
