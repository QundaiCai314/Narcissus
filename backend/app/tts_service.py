"""StepFun TTS is an independent binary-audio API, with NO implicit HTTP retry."""
import io
import wave
import httpx
from .config import settings

VOICES = {
    "cixingnansheng": "磁性男声", "wenrounvsheng": "温柔女声",
    "boyinnansheng": "播音男声", "jingdiannvsheng": "经典女声",
}


class SpeechError(Exception):
    def __init__(self, message, uncertain=False, retryable=False):
        super().__init__(message)
        self.uncertain, self.retryable = uncertain, retryable


def decode_wav(data):
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getcomptype()) != (1, 2, 24000, "NONE"):
                raise ValueError()
            frames = audio.readframes(audio.getnframes())
            if not frames or len(frames) != audio.getnframes() * 2 or len(frames) > 24000 * 2 * 240:
                raise ValueError()
            return frames
    except (ValueError, EOFError, wave.Error):
        raise SpeechError("语音结果格式或时长无效，请核查供应商请求后再重试", uncertain=True) from None


def encode_wav(frames):
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
        audio.writeframes(frames)
    return output.getvalue()


def synthesize(text, voice, model, base_url):
    s = settings()
    if not s.tts_api_key:
        raise SpeechError("尚未配置语音服务，请联系管理员")
    if voice not in VOICES or not 1 <= len(text) <= 1000:
        raise SpeechError("声音或朗读文本超出服务限制")
    try:
        with httpx.Client(timeout=httpx.Timeout(s.tts_timeout_seconds, connect=10), follow_redirects=False) as client:
            with client.stream("POST", base_url.rstrip("/") + "/audio/speech",
                headers={"Authorization": "Bearer " + s.tts_api_key},
                json={"model": model, "input": text, "voice": voice, "response_format": "wav", "sample_rate": 24000, "speed": 1.0}) as response:
                if response.status_code in (400, 401, 403, 404, 422, 429):
                    raise SpeechError("语音服务拒绝请求，请检查模型、声音、凭证或额度", retryable=response.status_code == 429)
                if response.status_code != 200:
                    raise SpeechError("语音请求结果不明，可能已计费；请核查后确认重试", uncertain=True)
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 12 * 1024 * 1024:
                        raise SpeechError("语音响应超过大小限制，可能已计费", uncertain=True)
                    chunks.append(chunk)
                data = b"".join(chunks)
                frames = decode_wav(data)
                return data, len(frames) // 48, {
                    "characters": len(text), "duration_ms": len(frames) // 48,
                    "provider_request_id": response.headers.get("x-request-id", "")[:200],
                    "provider_usage": None,
                }
    except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
        raise SpeechError("尚未连接语音服务，可安全重试", retryable=True) from None
    except httpx.HTTPError:
        raise SpeechError("语音请求中断或超时，结果不明且可能已计费；不会自动重发", uncertain=True) from None
