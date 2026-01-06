"""
VE3 Tool - Free AI Providers
============================
Cac AI provider mien phi de thay the Gemini:
- Ollama (FREE, local, chay tren may tinh cua ban)
- Groq (mien phi, rat nhanh)
- DeepSeek (re, chat nhat)
- OpenRouter (nhieu model mien phi)
- Google AI Studio (Gemini mien phi)
"""

import os
import json
import time
import requests
from typing import Optional, List, Dict, Any, Callable
from dataclasses import dataclass


@dataclass
class AIProvider:
    """Thong tin provider."""
    name: str
    api_key: str
    model: str
    endpoint: str


class OllamaClient:
    """
    Ollama API Client - FREE, chay LOCAL tren may tinh cua ban!

    Cai dat: https://ollama.ai
    Pull model: ollama pull qwen2.5:7b (nhanh) hoặc qwen2.5:14b (tốt hơn)

    Models khuyen dung:
    - qwen2.5:7b (Alibaba, nhanh, 32k context) ⭐ RECOMMENDED
    - qwen2.5:14b (Alibaba, cân bằng)
    - llama3.1:8b (Meta, 128k context)
    - mistral:7b (Mistral AI, cực nhanh)

    Endpoint mac dinh: http://localhost:11434
    """

    DEFAULT_ENDPOINT = "http://localhost:11434"

    MODELS = [
        "qwen2.5:7b",       # Alibaba Qwen 2.5 7B - Fast ⭐ DEFAULT
        "qwen2.5:14b",      # Alibaba Qwen 2.5 14B - Balanced
        "llama3.1:8b",      # Meta Llama 3.1 8B - 128k context
        "mistral:7b",       # Mistral 7B - Very fast
        "gemma3:27b",       # Google Gemma 3 27B - Slow but quality
    ]

    def __init__(self, model: str = None, endpoint: str = None):
        self.model = model or self.MODELS[0]
        self.endpoint = endpoint or self.DEFAULT_ENDPOINT
        self.chat_endpoint = f"{self.endpoint}/v1/chat/completions"

    def generate(
        self,
        prompt: str,
        system_prompt: str = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Optional[str]:
        """Generate text using Ollama (OpenAI compatible API)."""

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Content-Type": "application/json"
        }

        data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False
        }

        try:
            resp = requests.post(
                self.chat_endpoint,
                headers=headers,
                json=data,
                timeout=300  # Ollama local can be slow on first run
            )

            if resp.status_code == 200:
                result = resp.json()
                return result["choices"][0]["message"]["content"]
            else:
                print(f"[Ollama Error] {resp.status_code}: {resp.text[:200]}")
                return None

        except requests.exceptions.ConnectionError:
            print(f"[Ollama Error] Khong ket noi duoc! Chay 'ollama serve' truoc.")
            return None
        except requests.exceptions.Timeout:
            print(f"[Ollama Error] Timeout! Model co the dang load lan dau.")
            return None
        except Exception as e:
            print(f"[Ollama Error] {e}")
            return None

    def is_available(self) -> bool:
        """Check if Ollama is running."""
        try:
            resp = requests.get(f"{self.endpoint}/api/tags", timeout=5)
            return resp.status_code == 200
        except:
            return False

    def list_models(self) -> List[str]:
        """List available models in Ollama."""
        try:
            resp = requests.get(f"{self.endpoint}/api/tags", timeout=10)
            if resp.status_code == 200:
                data = resp.json()
                return [m["name"] for m in data.get("models", [])]
        except:
            pass
        return []


class DeepSeekClient:
    """
    DeepSeek API Client - Re va manh!

    Dang ky: https://platform.deepseek.com/api_keys
    Models:
    - deepseek-chat (tot nhat cho chat/reasoning)
    - deepseek-coder (tot cho code)

    Gia: ~$0.14/1M input tokens, ~$0.28/1M output tokens (rat re!)
    """

    ENDPOINT = "https://api.deepseek.com/v1/chat/completions"

    MODELS = [
        "deepseek-chat",      # Best for general use
        "deepseek-reasoner",  # For complex reasoning
    ]

    def __init__(self, api_key: str, model: str = None):
        self.api_key = api_key
        self.model = model or self.MODELS[0]

    def generate(
        self,
        prompt: str,
        system_prompt: str = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Optional[str]:
        """Generate text."""

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }

        try:
            resp = requests.post(
                self.ENDPOINT,
                headers=headers,
                json=data,
                timeout=120
            )

            if resp.status_code == 200:
                result = resp.json()
                return result["choices"][0]["message"]["content"]
            elif resp.status_code == 429:
                print(f"DeepSeek rate limit, waiting...")
                return None
            else:
                print(f"[DeepSeek Error] {resp.status_code}: {resp.text[:200]}")
                return None

        except Exception as e:
            print(f"[DeepSeek Error] {e}")
            return None
    

class GroqClient:
    """
    Groq API Client - Mien phi va rat nhanh!
    
    Dang ky: https://console.groq.com/keys
    Models mien phi:
    - llama-3.3-70b-versatile (tot nhat)
    - llama-3.1-8b-instant (nhanh)
    - mixtral-8x7b-32768
    """
    
    ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
    
    MODELS = [
        "llama-3.3-70b-versatile",  # Best
        "llama-3.1-70b-versatile",
        "llama-3.1-8b-instant",     # Fastest
        "mixtral-8x7b-32768",
        "gemma2-9b-it",
    ]
    
    def __init__(self, api_key: str, model: str = None):
        self.api_key = api_key
        self.model = model or self.MODELS[0]
    
    def generate(
        self,
        prompt: str,
        system_prompt: str = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Optional[str]:
        """Generate text."""
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        try:
            resp = requests.post(
                self.ENDPOINT,
                headers=headers,
                json=data,
                timeout=120
            )
            
            if resp.status_code == 200:
                result = resp.json()
                return result["choices"][0]["message"]["content"]
            else:
                print(f"[Groq Error] {resp.status_code}: {resp.text[:200]}")
                return None
                
        except Exception as e:
            print(f"[Groq Error] {e}")
            return None


class OpenRouterClient:
    """
    OpenRouter API Client - Nhieu model mien phi!
    
    Dang ky: https://openrouter.ai/keys
    Models mien phi:
    - meta-llama/llama-3.2-3b-instruct:free
    - google/gemma-2-9b-it:free
    - qwen/qwen-2-7b-instruct:free
    """
    
    ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
    
    FREE_MODELS = [
        "meta-llama/llama-3.2-3b-instruct:free",
        "google/gemma-2-9b-it:free",
        "qwen/qwen-2-7b-instruct:free",
        "microsoft/phi-3-mini-128k-instruct:free",
    ]
    
    def __init__(self, api_key: str, model: str = None):
        self.api_key = api_key
        self.model = model or self.FREE_MODELS[0]
    
    def generate(
        self,
        prompt: str,
        system_prompt: str = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Optional[str]:
        """Generate text."""
        
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://ve3tool.local",
            "X-Title": "VE3 Tool"
        }
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens
        }
        
        try:
            resp = requests.post(
                self.ENDPOINT,
                headers=headers,
                json=data,
                timeout=120
            )
            
            if resp.status_code == 200:
                result = resp.json()
                return result["choices"][0]["message"]["content"]
            else:
                print(f"[OpenRouter Error] {resp.status_code}: {resp.text[:200]}")
                return None
                
        except Exception as e:
            print(f"[OpenRouter Error] {e}")
            return None


class GeminiClient:
    """
    Google Gemini API Client.
    
    Dang ky: https://makersuite.google.com/app/apikey
    Models:
    - gemini-2.0-flash (moi nhat)
    - gemini-1.5-flash (nhanh)
    - gemini-1.5-pro (tot nhat)
    """
    
    ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    
    MODELS = [
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
    ]
    
    def __init__(self, api_key: str, model: str = None):
        self.api_key = api_key
        self.model = model or self.MODELS[0]
    
    def generate(
        self,
        prompt: str,
        system_prompt: str = None,
        temperature: float = 0.7,
        max_tokens: int = 4096
    ) -> Optional[str]:
        """Generate text."""
        
        url = self.ENDPOINT.format(model=self.model) + f"?key={self.api_key}"
        
        content = prompt
        if system_prompt:
            content = f"{system_prompt}\n\n{prompt}"
        
        data = {
            "contents": [{"parts": [{"text": content}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens
            }
        }
        
        try:
            resp = requests.post(url, json=data, timeout=120)
            
            if resp.status_code == 200:
                result = resp.json()
                return result["candidates"][0]["content"]["parts"][0]["text"]
            else:
                error_msg = resp.text[:300]
                print(f"[Gemini Error] {resp.status_code}: {error_msg}")
                
                # Check specific errors
                if "API key" in error_msg and "leaked" in error_msg:
                    raise Exception("API key bi leak! Vui long tao key moi.")
                elif resp.status_code == 429:
                    raise Exception("Rate limit! Doi 1 phut va thu lai.")
                
                return None
                
        except requests.exceptions.Timeout:
            print("[Gemini Error] Timeout")
            return None
        except Exception as e:
            print(f"[Gemini Error] {e}")
            raise


class MultiAIClient:
    """
    Client ho tro nhieu AI providers.
    Tu dong test va loai bo API khong hoat dong khi khoi tao.
    Thu tu uu tien: DeepSeek > Ollama (local fallback)
    """

    def __init__(self, config: Dict[str, Any], auto_filter: bool = True):
        """
        Config format:
        {
            "deepseek_api_keys": ["key1"],  # Primary - DeepSeek
            "ollama_model": "qwen2.5:7b",  # Fallback - Ollama local (fast, 32k context)
            "ollama_endpoint": "http://localhost:11434",  # Optional
        }

        auto_filter: Tu dong test va loai bo API khong hoat dong
        """
        self.config = config
        self.clients = []
        self._init_clients(auto_filter)

    def _test_client(self, name: str, client) -> bool:
        """Test 1 client voi request nho."""
        try:
            result = client.generate("Say OK", max_tokens=5)
            return result is not None
        except:
            return False

    def _init_clients(self, auto_filter: bool = True):
        """Khoi tao cac clients theo thu tu uu tien: DeepSeek > Ollama (local fallback)."""

        if auto_filter:
            print("\n[API Filter] Dang kiem tra API keys...")

        # 1. DeepSeek (PRIMARY - re, on dinh, manh)
        deepseek_keys = self.config.get("deepseek_api_keys", [])
        for i, key in enumerate(deepseek_keys):
            if key and key.strip():
                client = DeepSeekClient(key.strip())
                if auto_filter:
                    print(f"  Testing DeepSeek key #{i+1}...", end=" ")
                    if self._test_client("deepseek", client):
                        print("OK")
                        self.clients.append(("deepseek", client))
                    else:
                        print("SKIP (error)")
                else:
                    self.clients.append(("deepseek", client))

        # 2. Ollama (FALLBACK - LOCAL, FREE, khong rate limit!)
        ollama_model = self.config.get("ollama_model")
        if ollama_model:
            ollama_endpoint = self.config.get("ollama_endpoint", "http://localhost:11434")
            client = OllamaClient(model=ollama_model, endpoint=ollama_endpoint)
            if auto_filter:
                print(f"  Testing Ollama ({ollama_model})...", end=" ")
                if client.is_available():
                    # List models to confirm model exists
                    available_models = client.list_models()
                    if any(ollama_model in m for m in available_models):
                        print(f"OK (model found)")
                        self.clients.append(("ollama", client))
                    else:
                        print(f"SKIP (model '{ollama_model}' not found, available: {available_models[:3]})")
                else:
                    print("SKIP (ollama serve not running)")
            else:
                self.clients.append(("ollama", client))

        if auto_filter:
            # Count by provider type
            counts = {}
            for name, _ in self.clients:
                counts[name] = counts.get(name, 0) + 1

            result_parts = []
            if counts.get('deepseek', 0):
                result_parts.append(f"{counts['deepseek']} DeepSeek")
            if counts.get('ollama', 0):
                result_parts.append(f"{counts['ollama']} Ollama")

            print(f"[API Filter] Ket qua: {', '.join(result_parts) if result_parts else 'Khong co provider nao'}")

            if not self.clients:
                print("[API Filter] CANH BAO: Khong co API key nao hoat dong!")
            else:
                first_provider = self.clients[0][0] if self.clients else None
                if first_provider:
                    print(f"[API Filter] Se dung: {first_provider.capitalize()} (uu tien)")
    
    def generate(
        self,
        prompt: str,
        system_prompt: str = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        retry_count: int = 2
    ) -> Optional[str]:
        """
        Generate text, tu dong chuyen sang provider khac neu loi.
        Chi thu cac API da duoc filter la hoat dong.
        """

        if not self.clients:
            print("[MultiAI] Khong co AI provider nao hoat dong!")
            return None

        errors = []
        clients_to_remove = []

        for idx, (name, client) in enumerate(self.clients):
            for attempt in range(retry_count):
                try:
                    print(f"[MultiAI] {name.capitalize()} (attempt {attempt + 1})...")

                    result = client.generate(
                        prompt=prompt,
                        system_prompt=system_prompt,
                        temperature=temperature,
                        max_tokens=max_tokens
                    )

                    if result:
                        return result

                except Exception as e:
                    error_msg = str(e).lower()
                    errors.append(f"{name}: {str(e)[:50]}")

                    # Loi nghiem trong - xoa client nay
                    if "leaked" in error_msg or "quota" in error_msg or "unauthorized" in error_msg:
                        print(f"[MultiAI] {name} khong dung duoc, bo qua...")
                        clients_to_remove.append(idx)
                        break

                    # Rate limit - chuyen sang provider khac ngay
                    if "rate" in error_msg or "429" in error_msg:
                        print(f"[MultiAI] {name} rate limit, chuyen provider...")
                        break

                time.sleep(1)

        # Xoa cac client khong dung duoc
        for idx in reversed(clients_to_remove):
            if idx < len(self.clients):
                self.clients.pop(idx)

        if errors:
            print(f"[MultiAI] Tat ca providers failed")
        return None
    
    def get_available_providers(self) -> List[str]:
        """Tra ve danh sach providers kha dung."""
        return [name for name, _ in self.clients]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def create_ai_client(config: Dict[str, Any]) -> MultiAIClient:
    """Tao AI client tu config."""
    return MultiAIClient(config)


def test_providers():
    """Test cac providers."""
    
    print("=" * 50)
    print("Testing AI Providers")
    print("=" * 50)
    
    # Test Groq
    groq_key = os.environ.get("GROQ_API_KEY")
    if groq_key:
        print("\n[Testing Groq]")
        client = GroqClient(groq_key)
        result = client.generate("Say hello in Vietnamese")
        print(f"Result: {result[:100] if result else 'FAILED'}")
    
    # Test OpenRouter
    or_key = os.environ.get("OPENROUTER_API_KEY")
    if or_key:
        print("\n[Testing OpenRouter]")
        client = OpenRouterClient(or_key)
        result = client.generate("Say hello in Vietnamese")
        print(f"Result: {result[:100] if result else 'FAILED'}")
    
    # Test Gemini
    gemini_key = os.environ.get("GEMINI_API_KEY")
    if gemini_key:
        print("\n[Testing Gemini]")
        client = GeminiClient(gemini_key)
        try:
            result = client.generate("Say hello in Vietnamese")
            print(f"Result: {result[:100] if result else 'FAILED'}")
        except Exception as e:
            print(f"Error: {e}")


if __name__ == "__main__":
    test_providers()
