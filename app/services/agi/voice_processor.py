"""
Voice Processor for AGI Guest Assistant
Handles voice-to-text (Whisper) and text-to-speech processing

Features:
- Speech-to-text using OpenAI Whisper
- Text-to-speech using OpenAI TTS
- Wake word detection ("Hey Baarez")
- Voice confirmation for critical actions
- Multi-language support
- Noise handling with confidence scoring
"""

import logging
import base64
import tempfile
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
from enum import Enum

logger = logging.getLogger("agi.voice_processor")


class ConfirmationType(str, Enum):
    """Types of actions requiring voice confirmation"""
    BOOKING_CREATION = "booking_creation"
    BOOKING_CANCELLATION = "booking_cancellation"
    PAYMENT = "payment"
    CHECKOUT = "checkout"
    ROOM_CHANGE = "room_change"
    TASK_CREATION = "task_creation"


# Wake word patterns (case-insensitive)
WAKE_WORDS = [
    r"\bhey\s+baarez\b",
    r"\bhi\s+baarez\b",
    r"\bbaarez\b",
    r"\bhey\s+glimmora\b",
    r"\bglimmora\s+assistant\b",
]

# Confirmation phrases (case-insensitive)
CONFIRMATION_PHRASES = {
    "positive": [
        r"\byes\b", r"\byeah\b", r"\byep\b", r"\bsure\b", r"\bconfirm\b",
        r"\bcorrect\b", r"\bthat's\s+right\b", r"\bgo\s+ahead\b", r"\bproceed\b",
        r"\bdo\s+it\b", r"\bokay\b", r"\bok\b", r"\baffirmative\b"
    ],
    "negative": [
        r"\bno\b", r"\bnope\b", r"\bcancel\b", r"\bstop\b", r"\bdon't\b",
        r"\bwait\b", r"\bhold\s+on\b", r"\bnever\s+mind\b", r"\bforget\s+it\b"
    ]
}


class VoiceProcessor:
    """
    Voice processing for AGI assistant.

    Features:
    - Speech-to-text using OpenAI Whisper
    - Text-to-speech using OpenAI TTS
    - Audio format handling
    - Language detection
    """

    def __init__(self):
        self.openai_client = None
        self._init_openai()

    def _init_openai(self):
        """Initialize OpenAI client for voice processing"""
        try:
            from openai import OpenAI
            from app.core.config import settings

            if settings.openai_api_key:
                self.openai_client = OpenAI(api_key=settings.openai_api_key)
                logger.info("OpenAI voice processor initialized")
            else:
                logger.warning("OpenAI API key not configured - voice processing unavailable")
        except ImportError:
            logger.warning("OpenAI package not installed - voice processing unavailable")
        except Exception as e:
            logger.error(f"Failed to initialize voice processor: {e}")

    @property
    def is_available(self) -> bool:
        """Check if voice processing is available"""
        return self.openai_client is not None

    async def transcribe_audio(
        self,
        audio_data: bytes,
        audio_format: str = "webm",
        language: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Transcribe audio to text using Whisper.

        Args:
            audio_data: Raw audio bytes
            audio_format: Audio format (webm, mp3, wav, m4a, etc.)
            language: Optional language code (en, es, fr, etc.)

        Returns:
            Transcription result with text and metadata
        """
        if not self.is_available:
            return {
                "success": False,
                "error": "Voice processing not available",
                "message": "Voice transcription is not configured. Please type your message instead."
            }

        temp_file = None
        try:
            # Write audio to temp file
            suffix = f".{audio_format}"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(audio_data)
                temp_file = f.name

            # Transcribe using Whisper
            with open(temp_file, "rb") as audio_file:
                params = {
                    "model": "whisper-1",
                    "file": audio_file,
                    "response_format": "verbose_json"
                }
                if language:
                    params["language"] = language

                transcription = self.openai_client.audio.transcriptions.create(**params)

            # Parse response
            result = {
                "success": True,
                "text": transcription.text,
                "language": getattr(transcription, 'language', language or 'en'),
                "duration": getattr(transcription, 'duration', None),
                "confidence": 0.95  # Whisper doesn't provide confidence scores
            }

            # Check for detected language
            if hasattr(transcription, 'language') and transcription.language:
                result["detected_language"] = transcription.language

            logger.info(f"Transcribed audio: '{transcription.text[:50]}...' (lang: {result['language']})")

            return result

        except Exception as e:
            logger.error(f"Error transcribing audio: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to transcribe audio. Please try again or type your message."
            }
        finally:
            # Clean up temp file
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except:
                    pass

    async def transcribe_base64_audio(
        self,
        base64_audio: str,
        audio_format: str = "webm",
        language: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Transcribe base64-encoded audio.

        Args:
            base64_audio: Base64-encoded audio data
            audio_format: Audio format
            language: Optional language code

        Returns:
            Transcription result
        """
        try:
            # Remove data URL prefix if present
            if "," in base64_audio:
                base64_audio = base64_audio.split(",")[1]

            # Decode base64
            audio_data = base64.b64decode(base64_audio)

            return await self.transcribe_audio(audio_data, audio_format, language)

        except Exception as e:
            logger.error(f"Error decoding base64 audio: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Invalid audio data. Please try recording again."
            }

    async def text_to_speech(
        self,
        text: str,
        voice: str = "alloy",
        model: str = "tts-1",
        response_format: str = "mp3",
        speed: float = 1.0
    ) -> Dict[str, Any]:
        """
        Convert text to speech using OpenAI TTS.

        Args:
            text: Text to convert to speech
            voice: Voice to use (alloy, echo, fable, onyx, nova, shimmer)
            model: TTS model (tts-1, tts-1-hd)
            response_format: Output format (mp3, opus, aac, flac)
            speed: Speech speed (0.25 to 4.0)

        Returns:
            Audio data and metadata
        """
        if not self.is_available:
            return {
                "success": False,
                "error": "Voice processing not available",
                "message": "Text-to-speech is not configured."
            }

        try:
            # Limit text length
            if len(text) > 4096:
                text = text[:4096]
                logger.warning("Text truncated for TTS")

            response = self.openai_client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                response_format=response_format,
                speed=speed
            )

            # Get audio bytes
            audio_data = response.content

            # Encode to base64 for easy transfer
            audio_base64 = base64.b64encode(audio_data).decode('utf-8')

            return {
                "success": True,
                "audio_base64": audio_base64,
                "audio_format": response_format,
                "voice": voice,
                "text_length": len(text),
                "content_type": f"audio/{response_format}"
            }

        except Exception as e:
            logger.error(f"Error generating speech: {e}")
            return {
                "success": False,
                "error": str(e),
                "message": "Unable to generate speech."
            }

    async def detect_language(
        self,
        audio_data: bytes,
        audio_format: str = "webm"
    ) -> Dict[str, Any]:
        """
        Detect language from audio.

        Args:
            audio_data: Raw audio bytes
            audio_format: Audio format

        Returns:
            Language detection result
        """
        if not self.is_available:
            return {
                "success": False,
                "detected_language": "en",
                "confidence": 0.0
            }

        temp_file = None
        try:
            suffix = f".{audio_format}"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
                f.write(audio_data)
                temp_file = f.name

            with open(temp_file, "rb") as audio_file:
                transcription = self.openai_client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json"
                )

            return {
                "success": True,
                "detected_language": getattr(transcription, 'language', 'en'),
                "confidence": 0.9
            }

        except Exception as e:
            logger.error(f"Error detecting language: {e}")
            return {
                "success": False,
                "detected_language": "en",
                "confidence": 0.0,
                "error": str(e)
            }
        finally:
            if temp_file and os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except:
                    pass

    def get_available_voices(self) -> Dict[str, Any]:
        """Get list of available TTS voices."""
        voices = {
            "alloy": {
                "name": "Alloy",
                "description": "Neutral and balanced",
                "gender": "neutral"
            },
            "echo": {
                "name": "Echo",
                "description": "Deep and authoritative",
                "gender": "male"
            },
            "fable": {
                "name": "Fable",
                "description": "Warm and expressive",
                "gender": "neutral"
            },
            "onyx": {
                "name": "Onyx",
                "description": "Deep and resonant",
                "gender": "male"
            },
            "nova": {
                "name": "Nova",
                "description": "Energetic and upbeat",
                "gender": "female"
            },
            "shimmer": {
                "name": "Shimmer",
                "description": "Clear and gentle",
                "gender": "female"
            }
        }

        return {
            "success": True,
            "voices": voices,
            "default": "alloy",
            "recommended_for_hotel": "nova"  # Friendly and professional
        }

    def get_supported_formats(self) -> Dict[str, Any]:
        """Get supported audio formats."""
        return {
            "input_formats": {
                "transcription": ["flac", "m4a", "mp3", "mp4", "mpeg", "mpga", "oga", "ogg", "wav", "webm"],
                "recommended": "webm"
            },
            "output_formats": {
                "tts": ["mp3", "opus", "aac", "flac"],
                "recommended": "mp3"
            },
            "max_file_size_mb": 25,
            "max_duration_minutes": 30
        }

    # ==================== WAKE WORD DETECTION ====================

    def detect_wake_word(self, text: str) -> Dict[str, Any]:
        """
        Detect wake word in transcribed text.

        Args:
            text: Transcribed text to check for wake word

        Returns:
            Wake word detection result with remaining command
        """
        text_lower = text.lower().strip()

        for pattern in WAKE_WORDS:
            match = re.search(pattern, text_lower, re.IGNORECASE)
            if match:
                # Extract the command after the wake word
                remaining_text = text[match.end():].strip()
                # Remove leading punctuation
                remaining_text = re.sub(r'^[,\.\!\?]+\s*', '', remaining_text)

                return {
                    "detected": True,
                    "wake_word": match.group(),
                    "command": remaining_text if remaining_text else None,
                    "confidence": 0.95,
                    "message": f"Wake word '{match.group()}' detected."
                }

        return {
            "detected": False,
            "wake_word": None,
            "command": text,  # Return original text as command
            "confidence": 0.0,
            "message": "No wake word detected."
        }

    async def transcribe_with_wake_word(
        self,
        audio_data: bytes,
        audio_format: str = "webm",
        language: Optional[str] = None,
        require_wake_word: bool = False
    ) -> Dict[str, Any]:
        """
        Transcribe audio and check for wake word.

        Args:
            audio_data: Raw audio bytes
            audio_format: Audio format
            language: Optional language code
            require_wake_word: If True, only process commands that start with wake word

        Returns:
            Transcription with wake word detection
        """
        # First transcribe
        transcription = await self.transcribe_audio(audio_data, audio_format, language)

        if not transcription.get("success"):
            return transcription

        text = transcription.get("text", "")

        # Check for wake word
        wake_result = self.detect_wake_word(text)

        result = {
            **transcription,
            "wake_word_detected": wake_result["detected"],
            "wake_word": wake_result["wake_word"],
            "command": wake_result["command"],
        }

        if require_wake_word and not wake_result["detected"]:
            result["should_process"] = False
            result["message"] = "Listening for 'Hey Baarez' to activate..."
        else:
            result["should_process"] = True

        return result

    # ==================== CONFIRMATION FLOWS ====================

    def parse_confirmation_response(self, text: str) -> Dict[str, Any]:
        """
        Parse user's response to a confirmation request.

        Args:
            text: User's response text

        Returns:
            Confirmation parsing result
        """
        text_lower = text.lower().strip()

        # Check for positive confirmation
        for pattern in CONFIRMATION_PHRASES["positive"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return {
                    "confirmed": True,
                    "response_type": "positive",
                    "confidence": 0.9,
                    "original_text": text
                }

        # Check for negative/cancel
        for pattern in CONFIRMATION_PHRASES["negative"]:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return {
                    "confirmed": False,
                    "response_type": "negative",
                    "confidence": 0.9,
                    "original_text": text
                }

        # Unclear response
        return {
            "confirmed": None,
            "response_type": "unclear",
            "confidence": 0.3,
            "original_text": text,
            "message": "I didn't catch that. Please say 'yes' to confirm or 'no' to cancel."
        }

    def generate_confirmation_prompt(
        self,
        action_type: ConfirmationType,
        action_details: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Generate a voice confirmation prompt for critical actions.

        Args:
            action_type: Type of action requiring confirmation
            action_details: Details about the action

        Returns:
            Confirmation prompt with TTS text
        """
        prompts = {
            ConfirmationType.BOOKING_CREATION: (
                f"I'm about to create a booking for {action_details.get('room_type', 'a room')} "
                f"from {action_details.get('check_in', 'check-in date')} to {action_details.get('check_out', 'check-out date')}. "
                f"The total will be {action_details.get('total', 'calculated at checkout')}. "
                "Should I proceed with this booking?"
            ),
            ConfirmationType.BOOKING_CANCELLATION: (
                f"I'm about to cancel your booking with confirmation code {action_details.get('confirmation_code', 'N/A')}. "
                f"{action_details.get('cancellation_fee', 'Cancellation fees may apply')}. "
                "Are you sure you want to cancel?"
            ),
            ConfirmationType.PAYMENT: (
                f"I'm about to charge {action_details.get('amount', 'the amount')} to "
                f"{action_details.get('payment_method', 'your card on file')}. "
                "Do you authorize this payment?"
            ),
            ConfirmationType.CHECKOUT: (
                f"Your balance is {action_details.get('balance', '$0.00')}. "
                f"Should I process your checkout for room {action_details.get('room_number', 'your room')}?"
            ),
            ConfirmationType.ROOM_CHANGE: (
                f"I'll change your room from {action_details.get('current_room', 'current room')} "
                f"to {action_details.get('new_room', 'new room')}. "
                f"{action_details.get('fee_info', '')} "
                "Should I proceed?"
            ),
            ConfirmationType.TASK_CREATION: (
                f"I'm creating a {action_details.get('task_type', 'service')} request for "
                f"room {action_details.get('room_number', 'your room')}: {action_details.get('description', '')}. "
                "Is that correct?"
            ),
        }

        prompt_text = prompts.get(action_type, "Should I proceed with this action?")

        return {
            "action_type": action_type.value,
            "prompt_text": prompt_text,
            "action_details": action_details,
            "requires_confirmation": True,
            "timeout_seconds": 30,
            "reprompt_after_seconds": 10
        }

    async def request_voice_confirmation(
        self,
        action_type: ConfirmationType,
        action_details: Dict[str, Any],
        voice: str = "nova"
    ) -> Dict[str, Any]:
        """
        Generate voice prompt for confirmation.

        Args:
            action_type: Type of action requiring confirmation
            action_details: Details about the action
            voice: TTS voice to use

        Returns:
            Confirmation prompt with audio
        """
        prompt = self.generate_confirmation_prompt(action_type, action_details)

        # Generate TTS for the prompt
        tts_result = await self.text_to_speech(
            text=prompt["prompt_text"],
            voice=voice,
            speed=0.9  # Slightly slower for clarity
        )

        return {
            **prompt,
            "audio": tts_result.get("audio_base64"),
            "audio_format": tts_result.get("audio_format", "mp3"),
            "success": tts_result.get("success", False)
        }

    # ==================== NOISE HANDLING ====================

    def assess_audio_quality(
        self,
        transcription_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Assess the quality of audio transcription and provide hints.

        Args:
            transcription_result: Result from transcribe_audio

        Returns:
            Quality assessment with recommendations
        """
        if not transcription_result.get("success"):
            return {
                "quality": "failed",
                "score": 0.0,
                "issues": ["transcription_failed"],
                "recommendations": ["Please try speaking again in a quieter environment."]
            }

        text = transcription_result.get("text", "")
        confidence = transcription_result.get("confidence", 0.5)
        duration = transcription_result.get("duration")

        issues = []
        recommendations = []
        quality_score = confidence

        # Check for very short audio (might be cut off)
        if duration and duration < 1.0:
            issues.append("audio_too_short")
            recommendations.append("Try speaking a bit longer and more clearly.")
            quality_score -= 0.2

        # Check for empty or minimal transcription
        word_count = len(text.split())
        if word_count < 2:
            issues.append("minimal_content")
            recommendations.append("Could you please repeat that? I only caught a few words.")
            quality_score -= 0.2

        # Check for common noise indicators in transcription
        noise_indicators = [
            r"\[.*?\]",  # Bracketed noise descriptions
            r"\(.*?\)",  # Parenthetical noise descriptions
            r"um+", r"uh+", r"hmm+",  # Filler sounds
            r"\.{3,}",  # Extended pauses
        ]

        for pattern in noise_indicators:
            if re.search(pattern, text.lower()):
                issues.append("background_noise")
                recommendations.append("There seems to be some background noise. Try speaking closer to the microphone.")
                quality_score -= 0.1
                break

        # Determine overall quality
        if quality_score >= 0.8:
            quality = "excellent"
        elif quality_score >= 0.6:
            quality = "good"
        elif quality_score >= 0.4:
            quality = "fair"
        else:
            quality = "poor"

        return {
            "quality": quality,
            "score": max(0.0, min(1.0, quality_score)),
            "word_count": word_count,
            "duration": duration,
            "issues": issues,
            "recommendations": recommendations,
            "can_proceed": quality_score >= 0.4
        }

    async def transcribe_with_quality_check(
        self,
        audio_data: bytes,
        audio_format: str = "webm",
        language: Optional[str] = None,
        min_quality_score: float = 0.4
    ) -> Dict[str, Any]:
        """
        Transcribe audio with quality assessment.

        Args:
            audio_data: Raw audio bytes
            audio_format: Audio format
            language: Optional language code
            min_quality_score: Minimum quality score to accept

        Returns:
            Transcription with quality assessment
        """
        transcription = await self.transcribe_audio(audio_data, audio_format, language)
        quality = self.assess_audio_quality(transcription)

        result = {
            **transcription,
            "quality_assessment": quality
        }

        if quality["score"] < min_quality_score:
            result["needs_retry"] = True
            result["retry_message"] = quality["recommendations"][0] if quality["recommendations"] else "Please try again."

        return result

    # ==================== MULTI-LANGUAGE HELPERS ====================

    def get_supported_languages(self) -> Dict[str, Any]:
        """Get list of supported languages for voice processing."""
        return {
            "languages": [
                {"code": "en", "name": "English", "variants": ["en-US", "en-GB", "en-AU"]},
                {"code": "es", "name": "Spanish", "variants": ["es-ES", "es-MX"]},
                {"code": "fr", "name": "French", "variants": ["fr-FR", "fr-CA"]},
                {"code": "de", "name": "German", "variants": ["de-DE"]},
                {"code": "zh", "name": "Chinese", "variants": ["zh-CN", "zh-TW"]},
                {"code": "ja", "name": "Japanese", "variants": ["ja-JP"]},
                {"code": "hi", "name": "Hindi", "variants": ["hi-IN"]},
                {"code": "ar", "name": "Arabic", "variants": ["ar-SA", "ar-AE"]},
                {"code": "pt", "name": "Portuguese", "variants": ["pt-BR", "pt-PT"]},
                {"code": "it", "name": "Italian", "variants": ["it-IT"]},
                {"code": "ko", "name": "Korean", "variants": ["ko-KR"]},
                {"code": "ru", "name": "Russian", "variants": ["ru-RU"]},
            ],
            "default": "en",
            "auto_detect": True,
            "message": "Whisper supports automatic language detection for 97+ languages."
        }

    def get_localized_confirmation_prompts(self, language: str = "en") -> Dict[str, str]:
        """Get confirmation prompts in specified language."""
        prompts = {
            "en": {
                "confirm": "Please say 'yes' to confirm or 'no' to cancel.",
                "unclear": "I didn't quite catch that. Please say 'yes' or 'no'.",
                "timeout": "I haven't heard a response. The action has been cancelled for safety."
            },
            "es": {
                "confirm": "Por favor diga 'sí' para confirmar o 'no' para cancelar.",
                "unclear": "No entendí bien. Por favor diga 'sí' o 'no'.",
                "timeout": "No he recibido respuesta. La acción ha sido cancelada por seguridad."
            },
            "fr": {
                "confirm": "Veuillez dire 'oui' pour confirmer ou 'non' pour annuler.",
                "unclear": "Je n'ai pas bien compris. Veuillez dire 'oui' ou 'non'.",
                "timeout": "Je n'ai pas reçu de réponse. L'action a été annulée par sécurité."
            },
            "de": {
                "confirm": "Bitte sagen Sie 'ja' zum Bestätigen oder 'nein' zum Abbrechen.",
                "unclear": "Das habe ich nicht verstanden. Bitte sagen Sie 'ja' oder 'nein'.",
                "timeout": "Ich habe keine Antwort erhalten. Die Aktion wurde sicherheitshalber abgebrochen."
            }
        }
        return prompts.get(language, prompts["en"])


# Singleton instance
_voice_processor: Optional[VoiceProcessor] = None


def get_voice_processor() -> VoiceProcessor:
    """Get or create voice processor singleton."""
    global _voice_processor
    if _voice_processor is None:
        _voice_processor = VoiceProcessor()
    return _voice_processor
