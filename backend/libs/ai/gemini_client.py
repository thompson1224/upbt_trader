from __future__ import annotations
"""Gemini API 클라이언트 - 감성 분석 및 시장 인사이트"""
import asyncio
import json
import logging
from typing import TypedDict

import google.generativeai as genai

from libs.config import get_settings

logger = logging.getLogger(__name__)

SENTIMENT_SYSTEM_PROMPT = """당신은 암호화폐 시장 분석 전문가입니다.
주어진 시장 데이터를 분석하여 투자 감성을 평가하세요.

반드시 다음 JSON 형식으로만 응답하세요 (다른 텍스트 없이):
{
  "sentiment_score": -1.0 ~ 1.0,
  "confidence": 0.0 ~ 1.0,
  "summary": "3줄 이내 핵심 분석",
  "keywords": ["키워드1", "키워드2", "키워드3"],
  "reasoning": "구체적 근거"
}"""


class SentimentResult(TypedDict):
    sentiment_score: float
    confidence: float
    summary: str
    keywords: list[str]
    reasoning: str


_CALL_INTERVAL_SEC = 3.0   # 호출 간 최소 간격 (최대 ~20 RPM, Free Tier 30 RPM 한도 대응)


class GeminiClient:
    """Gemini API를 사용한 감성 분석 클라이언트."""

    def __init__(self):
        settings = get_settings()
        genai.configure(api_key=settings.gemini_api_key)
        self.model = genai.GenerativeModel(
            model_name=settings.gemini_model,
            system_instruction=SENTIMENT_SYSTEM_PROMPT,
        )
        self._lock = asyncio.Lock()
        self._last_call_time: float = 0.0

    async def analyze_sentiment(
        self,
        market: str,
        current_price: float,
        price_change_24h: float,
        volume_24h: float,
        news_snippets: list[str] | None = None,
        ta_context: str | None = None,
    ) -> SentimentResult | None:
        """
        시장 감성 분석.
        실패 시 None 반환 → TA-only 모드 폴백.
        """
        prompt = self._build_prompt(
            market, current_price, price_change_24h, volume_24h,
            news_snippets, ta_context,
        )

        try:
            async with self._lock:
                now = asyncio.get_event_loop().time()
                wait = _CALL_INTERVAL_SEC - (now - self._last_call_time)
                if wait > 0:
                    await asyncio.sleep(wait)
                self._last_call_time = asyncio.get_event_loop().time()

            response = await self.model.generate_content_async(prompt)
            raw_text = response.text.strip()

            # JSON 블록 추출
            if "```" in raw_text:
                raw_text = raw_text.split("```")[1]
                if raw_text.startswith("json"):
                    raw_text = raw_text[4:]

            result = json.loads(raw_text)
            return self._validate_result(result)

        except json.JSONDecodeError as e:
            logger.warning("Gemini JSON parse error for %s: %s", market, e)
            return None
        except Exception as e:
            logger.error("Gemini API error for %s: %s", market, e)
            return None

    def _build_prompt(
        self,
        market: str,
        current_price: float,
        price_change_24h: float,
        volume_24h: float,
        news_snippets: list[str] | None,
        ta_context: str | None,
    ) -> str:
        parts = [
            f"시장: {market}",
            f"현재가: {current_price:,.0f} KRW",
            f"24h 변동: {price_change_24h:+.2f}%",
            f"24h 거래량: {volume_24h:,.0f} KRW",
        ]
        if ta_context:
            parts.append(f"\n기술적 지표 현황:\n{ta_context}")
        if news_snippets:
            parts.append("\n관련 뉴스/공시:")
            parts.extend([f"- {s}" for s in news_snippets[:5]])

        return "\n".join(parts)

    def _validate_result(self, result: dict) -> SentimentResult:
        return SentimentResult(
            sentiment_score=max(-1.0, min(1.0, float(result.get("sentiment_score", 0)))),
            confidence=max(0.0, min(1.0, float(result.get("confidence", 0.5)))),
            summary=str(result.get("summary", ""))[:500],
            keywords=list(result.get("keywords", []))[:10],
            reasoning=str(result.get("reasoning", ""))[:1000],
        )
