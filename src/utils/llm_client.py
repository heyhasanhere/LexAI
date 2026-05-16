from openai import OpenAI

_PROVIDER_URLS: dict[str, str] = {
    "openai":    "https://api.openai.com/v1",
    "groq":      "https://api.groq.com/openai/v1",
    "together":  "https://api.together.xyz/v1",
    "openrouter": "https://openrouter.ai/api/v1",
    "gemini":    "https://generativelanguage.googleapis.com/v1beta/openai/",
    "mistral":   "https://api.mistral.ai/v1",
    "vllm":      "http://localhost:8080/v1",
}

PROVIDER_DEFAULT_MODELS: dict[str, str] = {
    "vllm":       "Qwen/Qwen3-4B-AWQ",
    "openai":     "gpt-4o-mini",
    "groq":       "llama-3.1-8b-instant",
    "together":   "meta-llama/Llama-3.2-3B-Instruct-Turbo",
    "openrouter": "meta-llama/llama-3.1-8b-instruct:free",
    "gemini":     "gemini-2.0-flash-lite",
    "mistral":    "mistral-small-latest",
}


def get_client(provider: str, base_url: str | None, api_key: str) -> OpenAI:
    url = base_url or _PROVIDER_URLS.get(provider, "http://localhost:8080/v1")
    return OpenAI(base_url=url, api_key=api_key)


def chat_extra_body(provider: str) -> dict:
    """vLLM needs thinking suppression for Qwen3; all other providers reject unknown fields."""
    if provider == "vllm":
        return {"chat_template_kwargs": {"enable_thinking": False}}
    return {}
