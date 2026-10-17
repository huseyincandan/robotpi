import json
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

from config import LLM
from services import llm
from services.assistant import AssistantService
from services.intent import IntentService


def response(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.dict(LLM, {"PROVIDER": "qwen"})
        self.config.start()
        self.addCleanup(self.config.stop)

    def test_local_client_uses_loopback_and_never_environment_api_key(self):
        with patch("services.llm.OpenAI") as constructor:
            llm.create_client()
        options = constructor.call_args.kwargs
        self.assertEqual(options["base_url"], "http://127.0.0.1:8081/v1")
        self.assertEqual(options["api_key"], "local-qwen")
        self.assertEqual(options["max_retries"], 0)

    def test_local_requests_override_all_original_model_names_and_disable_thinking(self):
        for original in ["gpt-4o", "gpt-4o-mini"]:
            with self.subTest(model=original):
                client = MagicMock()
                llm.complete(client, original, [{"role": "user", "content": "Merhaba"}])
                options = client.chat.completions.create.call_args.kwargs
                self.assertEqual(options["model"], LLM["MODEL"])
                self.assertFalse(options["extra_body"]["chat_template_kwargs"]["enable_thinking"])
                self.assertEqual(options["max_tokens"], LLM["MAX_TOKENS"])

    def test_json_schema_constrains_intent_types(self):
        client = MagicMock()
        llm.complete(client, "original", [], temperature=0, schema=llm.INTENT_SCHEMA)
        options = client.chat.completions.create.call_args.kwargs
        self.assertEqual(options["temperature"], 0)
        self.assertEqual(options["response_format"]["type"], "json_schema")
        self.assertEqual(options["response_format"]["json_schema"]["schema"], llm.INTENT_SCHEMA)

    def test_openai_switch_restores_original_request_and_json_format(self):
        with patch.dict(LLM, {"PROVIDER": "openai"}):
            client = MagicMock()
            llm.complete(client, "gpt-4o-mini", [], schema=llm.INTENT_SCHEMA)
            options = client.chat.completions.create.call_args.kwargs
            self.assertEqual(options["model"], "gpt-4o-mini")
            self.assertEqual(options["response_format"], {"type": "json_object"})
            self.assertNotIn("extra_body", options)
            with patch("services.llm.OpenAI") as constructor:
                llm.create_client()
                constructor.assert_called_once_with()

    def test_failed_local_request_does_not_fall_back(self):
        client = MagicMock()
        client.chat.completions.create.side_effect = ConnectionError("offline")
        with self.assertRaises(ConnectionError):
            llm.complete(client, "gpt-4o", [])
        client.chat.completions.create.assert_called_once()


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.dict(LLM, {"PROVIDER": "qwen"})
        self.config.start()
        self.addCleanup(self.config.stop)

    def test_chat_uses_qwen_and_keeps_conversation(self):
        assistant = AssistantService()
        assistant.client = MagicMock()
        assistant.client.chat.completions.create.return_value = response("Merhaba Hüseyin.")
        self.assertEqual(assistant.ask("Merhaba"), "Merhaba Hüseyin.")
        options = assistant.client.chat.completions.create.call_args.kwargs
        self.assertEqual(options["model"], LLM["MODEL"])
        self.assertEqual(assistant.messages[-1]["content"], "Merhaba Hüseyin.")

    def test_intent_uses_qwen_and_rejects_unknown_actions(self):
        service = IntentService()
        service.client = MagicMock()
        with patch.object(service, "_classify_local", return_value=None):
            for invalid in ['{"type":"invented","query":""}', '[]', 'null', '{"type":']:
                service.client.chat.completions.create.return_value = response(invalid)
                self.assertEqual(service.classify("bir şey"), {"type": "chat", "query": ""})
        options = service.client.chat.completions.create.call_args.kwargs
        self.assertEqual(options["model"], LLM["MODEL"])

    def test_web_plan_uses_qwen_and_preserves_explicit_city_and_day(self):
        assistant = AssistantService()
        assistant.client = MagicMock()
        assistant.client.chat.completions.create.return_value = response(json.dumps({
            "source": "weather", "city": "Ankara", "query": "Ankara hava durumu", "day": "tomorrow"
        }))
        plan = assistant._web_plan("Ankara'da yarın hava nasıl?", "hava")
        self.assertEqual(plan["source"], "weather")
        self.assertEqual(plan["city"], "Ankara")
        self.assertEqual(plan["day"], "tomorrow")
        options = assistant.client.chat.completions.create.call_args.kwargs
        self.assertEqual(options["model"], LLM["MODEL"])
        self.assertEqual(options["response_format"]["json_schema"]["schema"], llm.WEB_PLAN_SCHEMA)

    def test_web_answer_uses_qwen_with_search_context(self):
        assistant = AssistantService()
        assistant.client = MagicMock()
        assistant.client.chat.completions.create.return_value = response("Hava açık.")
        with patch.object(assistant, "_web_context", return_value="Ankara: açık, 20 derece"):
            self.assertEqual(assistant.ask_with_web("Hava nasıl?"), "Hava açık.")
        options = assistant.client.chat.completions.create.call_args.kwargs
        self.assertEqual(options["model"], LLM["MODEL"])
        self.assertIn("20 derece", options["messages"][-1]["content"])


if __name__ == "__main__":
    unittest.main()
