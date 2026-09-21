import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from app.services.model_manager import ModelConfigurationError, ModelManager
from app.services.model_manager import finish_llm_trace, start_llm_trace


class FakeChatModel:
    def __init__(self, label: str, fail: bool = False):
        self.label = label
        self.fail = fail
        self.calls = 0

    def invoke(self, input_value, config=None, **kwargs):
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"{self.label} failed")
        return AIMessage(content=f"{self.label}: ok")


class TestableModelManager(ModelManager):
    def __init__(self, fake_models, **kwargs):
        super().__init__(**kwargs)
        self.fake_models = fake_models

    def _build_model(self, provider: str, model_config=None):
        return self.fake_models[provider]


class ModelManagerTest(unittest.TestCase):
    def test_openai_model_requires_configured_api_key(self):
        manager = ModelManager(provider="openai", enable_fallback=False)

        with patch("app.services.model_manager.OPENAI_API_KEY", ""):
            with self.assertRaisesRegex(
                RuntimeError,
                "OPENAI_API_KEY is not configured",
            ):
                manager._build_model("openai")

    def test_switch_provider_updates_status(self):
        manager = TestableModelManager(
            fake_models={
                "ollama": FakeChatModel("ollama"),
                "openai": FakeChatModel("openai"),
            },
            provider="ollama",
            fallback_provider="ollama",
        )

        status = manager.set_provider("openai")

        self.assertEqual(status["provider"], "openai")

    def test_invoke_uses_current_provider(self):
        manager = TestableModelManager(
            fake_models={
                "ollama": FakeChatModel("ollama"),
                "openai": FakeChatModel("openai"),
            },
            provider="openai",
            fallback_provider="ollama",
        )

        result = manager.invoke("hello")

        self.assertEqual(result.content, "openai: ok")
        self.assertEqual(manager.last_provider, "openai")

    def test_falls_back_to_local_model_when_primary_fails(self):
        manager = TestableModelManager(
            fake_models={
                "ollama": FakeChatModel("ollama"),
                "openai": FakeChatModel("openai", fail=True),
            },
            provider="openai",
            fallback_provider="ollama",
            enable_fallback=True,
        )

        result = manager.invoke("hello")

        self.assertEqual(result.content, "ollama: ok")
        self.assertEqual(manager.last_provider, "ollama")
        self.assertIn("openai", manager.last_error)

    def test_configuration_error_never_falls_back_to_another_provider(self):
        fallback_model = FakeChatModel("ollama")
        manager = ModelManager(
            provider="openai",
            fallback_provider="ollama",
            enable_fallback=True,
        )

        def build_model(provider, model_config=None):
            if provider == "openai":
                raise ModelConfigurationError("OPENAI_API_KEY is not configured")
            return fallback_model

        with patch.object(manager, "_build_model", side_effect=build_model):
            with self.assertRaises(ModelConfigurationError):
                manager.invoke("hello")

        self.assertEqual(fallback_model.calls, 0)

    def test_trace_records_llm_call_duration(self):
        manager = TestableModelManager(
            fake_models={
                "ollama": FakeChatModel("ollama"),
                "openai": FakeChatModel("openai"),
            },
            provider="openai",
            fallback_provider="ollama",
        )

        token = start_llm_trace()
        manager.invoke("hello")
        events = finish_llm_trace(token)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["provider"], "openai")
        self.assertTrue(events[0]["success"])
        self.assertFalse(events[0]["fallback"])
        self.assertEqual(events[0]["task"], "primary")
        self.assertIn("duration_sec", events[0])

    def test_task_llm_records_task_name(self):
        manager = TestableModelManager(
            fake_models={
                "ollama": FakeChatModel("ollama"),
                "openai": FakeChatModel("openai"),
            },
            provider="openai",
            fallback_provider="ollama",
        )

        token = start_llm_trace()
        result = manager.get_llm(task="rag_summary").invoke("hello")
        events = finish_llm_trace(token)

        self.assertEqual(result.content, "openai: ok")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["task"], "rag_summary")
        self.assertEqual(events[0]["provider"], "openai")
        self.assertEqual(events[0]["model"], "gpt-5.5")

    def test_trace_records_fallback_call_duration(self):
        manager = TestableModelManager(
            fake_models={
                "ollama": FakeChatModel("ollama"),
                "openai": FakeChatModel("openai", fail=True),
            },
            provider="openai",
            fallback_provider="ollama",
            enable_fallback=True,
        )

        token = start_llm_trace()
        manager.invoke("hello")
        events = finish_llm_trace(token)

        self.assertEqual(len(events), 2)
        self.assertFalse(events[0]["success"])
        self.assertEqual(events[0]["provider"], "openai")
        self.assertTrue(events[1]["success"])
        self.assertTrue(events[1]["fallback"])
        self.assertEqual(events[1]["provider"], "ollama")

    def test_raises_when_fallback_disabled(self):
        manager = TestableModelManager(
            fake_models={
                "ollama": FakeChatModel("ollama"),
                "openai": FakeChatModel("openai", fail=True),
            },
            provider="openai",
            fallback_provider="ollama",
            enable_fallback=False,
        )

        with self.assertRaises(RuntimeError):
            manager.invoke("hello")


if __name__ == "__main__":
    unittest.main()
