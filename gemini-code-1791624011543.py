import hashlib
import os
from datetime import datetime
from typing import Literal, Optional
from urllib.parse import quote

from fastapi import Depends, FastAPI, File, HTTPException, Response, Security, UploadFile, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

# ==============================================================================
# 1. AYARLAR VE ORTAM DEĞİŞKENLERİ
# ==============================================================================
TOKEN_HASH_PEPPER = os.getenv("TOKEN_HASH_PEPPER", "secret_pepper")

# ==============================================================================
# 2. PYDANTIC ŞEMALARI (ai/schema.json UYUMLU)
# ==============================================================================
CategoryType = Literal[
    "sport", "study", "work", "meeting", "health", "social", "personal", "other"
]
IntentType = Literal["create_plan", "clarify", "unsupported"]


class ParsedPlan(BaseModel):
    intent: IntentType = Field(..., description="Kullanıcı niyeti")
    title: Optional[str] = Field(None, description="Planlanan eylemin kısa adı")
    category: Optional[CategoryType] = Field(None, description="Eylem kategorisi")
    date: Optional[str] = Field(None, description="YYYY-MM-DD formatında tarih")
    time: Optional[str] = Field(None, description="HH:MM formatında saat")
    duration_minutes: Optional[int] = Field(60, ge=5, le=1440, description="Süre (dk)")
    recurrence: Optional[str] = Field(None, description="RRULE formatı")
    language: Literal["tr", "en"] = Field("tr", description="Konuşma dili")
    needs_weather_check: bool = Field(False, description="Dış mekan aktivitesi mi?")
    clarification_question: Optional[str] = Field(None, description="Soru metni")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Güven skoru")


class OutcomeReport(BaseModel):
    status: Literal["done", "postponed", "skipped"]
    reported_via: Optional[str] = "device"
    note: Optional[str] = None


class TelemetryReport(BaseModel):
    action: str = "ping"
    wifi_rssi: Optional[int] = None
    battery_pct: Optional[int] = None
    free_heap_bytes: Optional[int] = None
    last_error: Optional[str] = None


# ==============================================================================
# 3. KİMLİK DOĞRULAMA (MOCK BEARING TOKEN)
# ==============================================================================
security = HTTPBearer()


def verify_device_token(
    credentials: HTTPAuthorizationCredentials = Security(security),
) -> dict:
    """
    Cihaz token doğrulamasını SHA-256 + PEPPER ile bellek seviyesinde simüle eder.
    """
    raw_token = credentials.credentials
    if not raw_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "unauthorized", "message": "Token bulunamadı"},
        )

    token_bytes = (raw_token + TOKEN_HASH_PEPPER).encode("utf-8")
    token_hash = hashlib.sha256(token_bytes).hexdigest()

    return {
        "id": "mock-user-uuid-1234",
        "display_name": "Test User",
        "timezone": "Europe/Istanbul",
        "token_hash": token_hash,
    }


# ==============================================================================
# 4. FASTAPI UYGULAMASI VE UÇ NOKTALAR (ENDPOINTS)
# ==============================================================================
app = FastAPI(
    title="GAP FastAPI Skeleton",
    description="Nebius Serverless & ESP32 Entegrasyon Sunucu İskeleti (Mock AI)",
    version="1.0.0",
)


@app.post("/voice", status_code=201)
async def handle_voice_input(
    audio: UploadFile = File(...),
    user_data: dict = Depends(verify_device_token),
):
    """
    3.1. Ses Kaydı Alma ve Yanıt Dönme (Groq ve Nemotron Modülleri Entegre Edilene Kadar Mock)
    """
    # 1. Ses boyutu kontrolü (Maksimum 320KB / ~10s)
    audio_bytes = await audio.read()
    if len(audio_bytes) > 320 * 1024:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": "payload_too_large",
                "message": "Ses dosyası 10 saniyeyi/320KB'ı aşamaz.",
            },
        )

    # 2. Mock STT Transkripti (Lider Groq entegrasyonunu tamamlayınca buraya bağlanacak)
    mock_transcript = "Yarın saat 18:00'de spor salonuna gideceğim."

    # 3. Mock Nemotron ParsedPlan Çıktısı (Hamza LLM modülünü tamamlayınca buraya bağlanacak)
    mock_parsed_plan = ParsedPlan(
        intent="create_plan",
        title="Spor salonu",
        category="sport",
        date=datetime.now().strftime("%Y-%m-%d"),
        time="18:00",
        duration_minutes=60,
        recurrence=None,
        language="tr",
        needs_weather_check=False,
        clarification_question=None,
        confidence=0.98,
    )

    # 4. Mock Yanıt Metni
    response_text = (
        f"Planınız kaydedildi. {mock_parsed_plan.date} saat {mock_parsed_plan.time} için "
        f"{mock_parsed_plan.title} planlandı."
    )

    # 5. Header bilgileri
    headers = {
        "X-Plan-ID": "mock-plan-uuid-5678",
        "X-Transcript": quote(mock_transcript),
        "X-Response-Text": quote(response_text),
    }

    # Groq TTS modülü bağlanana kadar boş WAV bytes döner
    return Response(content=b"", media_type="audio/wav", headers=headers)


@app.post("/plans/{plan_id}/outcome", status_code=201)
async def report_plan_outcome(
    plan_id: str,
    payload: OutcomeReport,
    user_data: dict = Depends(verify_device_token),
):
    """
    3.2. Fiziksel Buton Durum Bildirimi (done, postponed, skipped)
    """
    return {
        "id": "mock-outcome-uuid-9999",
        "plan_id": plan_id,
        "status": payload.status,
        "reported_via": payload.reported_via,
        "reported_at": datetime.now().isoformat(),
    }


@app.get("/me/upcoming")
async def get_upcoming_plans(
    since: Optional[str] = None,
    to: Optional[str] = None,
    user_data: dict = Depends(verify_device_token),
):
    """
    3.3. ESP32 Ekranı İçin Sıradaki Planı Çekme
    """
    return {
        "items": [
            {
                "plan_id": "mock-plan-uuid-5678",
                "title": "Koşu",
                "category": "sport",
                "planned_start": "2026-10-10T18:00:00+03:00",
                "reminder_at": "2026-10-10T17:45:00+03:00",
            }
        ]
    }


@app.post("/device/telemetry")
async def receive_telemetry(
    payload: TelemetryReport,
    user_data: dict = Depends(verify_device_token),
):
    """
    3.4. Donanım Sağlığı ve Ping Bildirimi
    """
    return {
        "status": "online",
        "server_time": datetime.now().isoformat(),
    }