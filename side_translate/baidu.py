from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


TRANSLATE_URL = "https://fanyi-api.baidu.com/api/trans/vip/translate"
TOKEN_URL = "https://aip.baidubce.com/oauth/2.0/token"
OCR_URL = "https://aip.baidubce.com/rest/2.0/ocr/v1/general_basic"
logger = logging.getLogger(__name__)


class BaiduError(RuntimeError):
    pass


@dataclass(frozen=True)
class Translation:
    source_language: str
    target_language: str
    source_text: str
    translated_text: str


class BaiduClient:
    def __init__(
        self,
        app_id: str,
        secret_key: str,
        ocr_api_key: str = "",
        ocr_secret_key: str = "",
        timeout: int = 20,
    ) -> None:
        self.app_id = app_id.strip()
        self.secret_key = secret_key.strip()
        self.ocr_api_key = ocr_api_key.strip()
        self.ocr_secret_key = ocr_secret_key.strip()
        self.timeout = timeout
        self._ocr_token = ""
        self._ocr_token_expires_at = 0.0

    @staticmethod
    def make_sign(app_id: str, text: str, salt: str, secret_key: str) -> str:
        raw = f"{app_id}{text}{salt}{secret_key}".encode("utf-8")
        return hashlib.md5(raw).hexdigest()

    def translate(self, text: str, source: str = "auto", target: str = "zh") -> Translation:
        text = text.strip()
        if not text:
            raise BaiduError("没有可翻译的文本")
        if not self.app_id or not self.secret_key:
            raise BaiduError("请先填写百度翻译 App ID 和密钥")

        started = time.perf_counter()
        logger.info(
            "translate.start characters=%d source=%s target=%s",
            len(text),
            source,
            target,
        )
        salt = secrets.token_hex(8)
        params = {
            "q": text,
            "from": source,
            "to": target,
            "appid": self.app_id,
            "salt": salt,
            "sign": self.make_sign(self.app_id, text, salt, self.secret_key),
        }
        payload = self._request_json(
            f"{TRANSLATE_URL}?{urllib.parse.urlencode(params)}",
            operation="translation",
        )
        if "error_code" in payload:
            raise BaiduError(self._translation_error(payload))

        items = payload.get("trans_result") or []
        if not items:
            raise BaiduError("百度翻译未返回结果")
        result = Translation(
            source_language=str(payload.get("from", source)),
            target_language=str(payload.get("to", target)),
            source_text="\n".join(str(item.get("src", "")) for item in items),
            translated_text="\n".join(str(item.get("dst", "")) for item in items),
        )
        logger.info(
            "translate.complete source_characters=%d translated_characters=%d elapsed_ms=%.1f",
            len(result.source_text),
            len(result.translated_text),
            _elapsed_ms(started),
        )
        return result

    def recognize(self, image_bytes: bytes) -> str:
        if not self.ocr_api_key or not self.ocr_secret_key:
            raise BaiduError("截图翻译需要填写百度 OCR API Key 和 Secret Key")
        if not image_bytes:
            raise BaiduError("截图内容为空")

        started = time.perf_counter()
        logger.info("ocr.start image_bytes=%d", len(image_bytes))
        token = self._get_ocr_token()
        encoding_started = time.perf_counter()
        body = urllib.parse.urlencode(
            {
                "image": base64.b64encode(image_bytes).decode("ascii"),
                "language_type": "CHN_ENG",
                "detect_direction": "true",
                "paragraph": "false",
                "probability": "false",
            }
        ).encode("ascii")
        logger.info(
            "ocr.encode.complete request_bytes=%d elapsed_ms=%.1f",
            len(body),
            _elapsed_ms(encoding_started),
        )
        payload = self._request_json(
            f"{OCR_URL}?access_token={urllib.parse.quote(token)}",
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            operation="ocr",
        )
        if "error_code" in payload:
            message = payload.get("error_msg", "未知错误")
            raise BaiduError(f"百度 OCR 失败：{message} ({payload['error_code']})")

        lines = [str(item.get("words", "")).strip() for item in payload.get("words_result", [])]
        text = "\n".join(line for line in lines if line)
        if not text:
            raise BaiduError("截图中没有识别到文字")
        logger.info(
            "ocr.complete lines=%d characters=%d elapsed_ms=%.1f",
            len(lines),
            len(text),
            _elapsed_ms(started),
        )
        return text

    def recognize_and_translate(
        self, image_bytes: bytes, source: str = "auto", target: str = "zh"
    ) -> Translation:
        return self.translate(self.recognize(image_bytes), source, target)

    def _get_ocr_token(self) -> str:
        if self._ocr_token and time.time() < self._ocr_token_expires_at:
            logger.info("ocr_auth.cache_hit")
            return self._ocr_token
        started = time.perf_counter()
        logger.info("ocr_auth.start cache_hit=false")
        params = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.ocr_api_key,
                "client_secret": self.ocr_secret_key,
            }
        )
        payload = self._request_json(
            f"{TOKEN_URL}?{params}",
            data=b"",
            operation="ocr-auth",
        )
        token = str(payload.get("access_token", ""))
        if not token:
            description = payload.get("error_description") or payload.get("error") or "无法获取访问令牌"
            raise BaiduError(f"百度 OCR 鉴权失败：{description}")
        self._ocr_token = token
        expires_in = int(payload.get("expires_in", 2_592_000))
        self._ocr_token_expires_at = time.time() + max(60, expires_in - 300)
        logger.info("ocr_auth.complete elapsed_ms=%.1f", _elapsed_ms(started))
        return token

    def _request_json(
        self,
        url: str,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        operation: str = "baidu",
    ) -> dict:
        request = urllib.request.Request(
            url,
            data=data,
            headers={"User-Agent": "SideTranslate/0.1", **(headers or {})},
        )
        started = time.perf_counter()
        logger.info(
            "http.start operation=%s request_bytes=%d timeout_seconds=%d",
            operation,
            len(data or b""),
            self.timeout,
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                logger.info(
                    "http.complete operation=%s status=%s response_bytes=%d elapsed_ms=%.1f",
                    operation,
                    getattr(response, "status", "unknown"),
                    len(raw),
                    _elapsed_ms(started),
                )
                return json.loads(raw.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            logger.warning(
                "http.failed operation=%s status=%d elapsed_ms=%.1f",
                operation,
                exc.code,
                _elapsed_ms(started),
            )
            try:
                detail = exc.read().decode("utf-8")
            except Exception:
                detail = str(exc)
            raise BaiduError(f"请求百度服务失败：HTTP {exc.code} {detail[:120]}") from exc
        except urllib.error.URLError as exc:
            logger.warning(
                "http.failed operation=%s reason=%s elapsed_ms=%.1f",
                operation,
                type(exc.reason).__name__,
                _elapsed_ms(started),
            )
            raise BaiduError(f"无法连接百度服务：{exc.reason}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning(
                "http.invalid_response operation=%s elapsed_ms=%.1f",
                operation,
                _elapsed_ms(started),
            )
            raise BaiduError("百度服务返回了无法解析的数据") from exc

    @staticmethod
    def _translation_error(payload: dict) -> str:
        code = str(payload.get("error_code", ""))
        known = {
            "52001": "请求超时，请重试",
            "52002": "系统错误，请重试",
            "52003": "未授权用户，请检查 App ID",
            "54000": "请求参数错误",
            "54001": "签名错误，请检查密钥",
            "54003": "访问频率过高，请稍后再试",
            "54004": "账户余额不足",
            "54005": "长文本请求过于频繁",
            "58000": "客户端 IP 非法",
            "58001": "目标语言不支持",
            "58002": "服务已关闭",
            "90107": "认证未通过或服务未开通",
        }
        message = known.get(code, str(payload.get("error_msg", "未知错误")))
        return f"百度翻译失败：{message} ({code})"


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000
