"""Local model clients. Anything with .extract(images, prompt, schema) -> str works."""
import base64
import json
import urllib.request


class OllamaClient:
    def __init__(self, model="qwen2.5vl:7b", host="http://localhost:11434", timeout=300):
        self.model, self.host, self.timeout = model, host.rstrip("/"), timeout

    def extract(self, images, prompt, schema=None):
        payload = {
            "model": self.model,
            "stream": False,
            "options": {"temperature": 0},
            "messages": [{
                "role": "user",
                "content": prompt,
                "images": [base64.b64encode(i).decode() for i in images],
            }],
        }
        if schema:
            payload["format"] = schema  # constrained decoding (Ollama >= 0.5)
        req = urllib.request.Request(
            f"{self.host}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.load(resp)["message"]["content"]

    def check(self):
        """Raise a friendly error if Ollama or the model is missing."""
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=5) as r:
                names = [m["name"] for m in json.load(r).get("models", [])]
        except OSError as e:
            raise SystemExit(f"Can't reach Ollama at {self.host}. Is it running? ({e})")
        if not any(n == self.model or n.split(":")[0] == self.model for n in names):
            raise SystemExit(f"Model '{self.model}' not found. Run: ollama pull {self.model}")
