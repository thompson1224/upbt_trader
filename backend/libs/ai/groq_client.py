from __future__ import annotations
"""Groq API 클라이언트 - 감성 분석 전용 (무료 14,400 req/day)"""
import asyncio
import json
import logging
from typing import TypedDict

import httpx

from libs.config import get_settings

logger = logging.getLogger(__name__)

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

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


class GroqClient:
    """Groq API를 사용한 감성 분석 클라이언트 (무료 14,400 req/day)."""

    def __init__(self):
        settings = get_settings()
        self._api_key = settings.groq_api_key
        self._model = settings.groq_model
        self._semaphore = asyncio.Semaphore(5)

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
        if not self._api_key:
            return None

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": SENTIMENT_SYSTEM_PROMPT},
                {"role": "user", "content": self._build_prompt(
                    market, current_price, price_change_24h,
                    volume_24h, news_snippets, ta_context,
                )},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
            "max_tokens": 512,
        }

        try:
            async with self._semaphore:
                async with httpx.AsyncClient(timeout=30.0) as client:
                    resp = await client.post(
                        GROQ_API_URL,
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json=payload,
                    )
                    resp.raise_for_status()

            result = json.loads(resp.json()["choices"][0]["message"]["content"])
            return self._validate_result(result)

        except json.JSONDecodeError as e:
            logger.warning("Groq JSON parse error for %s: %s", market, e)
            return None
        except httpx.HTTPStatusError as e:
            logger.error("Groq HTTP error for %s: %s %s", market, e.response.status_code, e.response.text[:200])
            return None
        except Exception as e:
            logger.error("Groq error for %s: %s", market, e)
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
