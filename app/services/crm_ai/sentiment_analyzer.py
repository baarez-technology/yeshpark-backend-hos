"""
Sentiment Analyzer
Analyzes guest sentiment from text (feedback, reviews, chat messages)
"""
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import re


class SentimentAnalyzer:
    """Rule-based sentiment analyzer for guest communications"""

    def __init__(self, model_version: str = "1.0.0"):
        self.model_version = model_version
        self.model_name = "sentiment_analyzer_v1"

        # Positive sentiment keywords with weights
        self.positive_keywords = {
            # Strong positive
            "excellent": 0.9, "amazing": 0.9, "outstanding": 0.9, "perfect": 0.9,
            "exceptional": 0.9, "wonderful": 0.85, "fantastic": 0.85, "incredible": 0.85,
            "love": 0.8, "loved": 0.8, "best": 0.8, "awesome": 0.8,
            # Moderate positive
            "great": 0.7, "good": 0.6, "nice": 0.55, "pleasant": 0.6,
            "comfortable": 0.6, "clean": 0.55, "friendly": 0.65, "helpful": 0.65,
            "recommend": 0.7, "enjoyed": 0.7, "satisfied": 0.65, "happy": 0.7,
            # Mild positive
            "fine": 0.4, "okay": 0.35, "decent": 0.4, "adequate": 0.35,
        }

        # Negative sentiment keywords with weights
        self.negative_keywords = {
            # Strong negative
            "terrible": -0.9, "awful": -0.9, "horrible": -0.9, "worst": -0.9,
            "disgusting": -0.9, "unacceptable": -0.85, "nightmare": -0.85,
            "hate": -0.8, "hated": -0.8, "furious": -0.85, "appalling": -0.85,
            # Moderate negative
            "bad": -0.7, "poor": -0.65, "disappointing": -0.7, "disappointed": -0.7,
            "dirty": -0.65, "rude": -0.7, "slow": -0.5, "noisy": -0.55,
            "problem": -0.5, "issue": -0.45, "complaint": -0.6, "unhappy": -0.65,
            # Mild negative
            "mediocre": -0.4, "average": -0.25, "cold": -0.35, "small": -0.3,
            "expensive": -0.35, "wait": -0.3, "delay": -0.4,
        }

        # Emotion keywords
        self.emotion_keywords = {
            "happy": ["happy", "delighted", "pleased", "thrilled", "excited", "joy"],
            "satisfied": ["satisfied", "content", "comfortable", "relaxed", "peaceful"],
            "frustrated": ["frustrated", "annoyed", "irritated", "upset", "bothered"],
            "angry": ["angry", "furious", "outraged", "mad", "livid"],
            "disappointed": ["disappointed", "let down", "underwhelmed", "dissatisfied"],
        }

        # Aspect keywords for aspect-based sentiment
        self.aspects = {
            "room": ["room", "suite", "bed", "bathroom", "shower", "view", "balcony", "space"],
            "service": ["service", "staff", "reception", "concierge", "housekeeping", "response"],
            "food": ["food", "breakfast", "dinner", "restaurant", "dining", "meal", "coffee"],
            "location": ["location", "area", "neighborhood", "walking", "distance", "beach", "city"],
            "amenities": ["pool", "spa", "gym", "wifi", "parking", "facilities", "amenities"],
            "value": ["price", "value", "worth", "expensive", "cheap", "cost", "money"],
            "cleanliness": ["clean", "dirty", "spotless", "tidy", "hygiene", "sanitary"],
        }

        # Negation words that flip sentiment
        self.negation_words = ["not", "no", "never", "none", "nothing", "neither", "don't", "doesn't", "didn't", "won't", "wouldn't", "couldn't", "shouldn't", "isn't", "aren't", "wasn't", "weren't"]

        # Intensifiers
        self.intensifiers = {"very": 1.3, "extremely": 1.5, "really": 1.2, "absolutely": 1.4, "completely": 1.3, "totally": 1.3, "quite": 1.1, "so": 1.2}

    def analyze(self, text: str, source: str = "feedback") -> Dict[str, Any]:
        """Analyze sentiment of text"""
        if not text or len(text.strip()) == 0:
            return self._empty_result()

        # Preprocess text
        text_lower = text.lower()
        words = re.findall(r'\b\w+\b', text_lower)

        # Calculate base sentiment
        sentiment_score, matched_keywords = self._calculate_sentiment(words, text_lower)

        # Detect primary emotion
        primary_emotion, emotion_scores = self._detect_emotion(words)

        # Aspect-based sentiment
        aspect_sentiments = self._analyze_aspects(text_lower)

        # Calculate emotion intensity
        emotion_intensity = abs(sentiment_score)

        # Detect triggers (what caused the sentiment)
        triggers = self._detect_triggers(text_lower, matched_keywords, aspect_sentiments)

        # Get sentiment label
        sentiment_label = self._get_sentiment_label(sentiment_score)

        # Confidence based on keyword matches and text length
        confidence = self._calculate_confidence(matched_keywords, len(words))

        return {
            "sentiment_score": round(sentiment_score, 3),
            "sentiment_label": sentiment_label,
            "primary_emotion": primary_emotion,
            "emotion_scores": emotion_scores,
            "emotion_intensity": round(emotion_intensity, 2),
            "aspect_sentiments": aspect_sentiments,
            "triggers": triggers,
            "matched_keywords": matched_keywords[:10],
            "confidence": round(confidence, 2),
            "source": source,
            "text_length": len(text),
            "word_count": len(words),
            "model_version": self.model_version,
            "analysis_summary": self._generate_summary(sentiment_label, primary_emotion, triggers, aspect_sentiments),
        }

    def _calculate_sentiment(self, words: List[str], full_text: str) -> Tuple[float, List[Dict]]:
        """Calculate overall sentiment score"""
        total_score = 0.0
        matched = []
        word_count = len(words)

        for i, word in enumerate(words):
            # Check for negation in previous words
            has_negation = False
            for j in range(max(0, i - 3), i):
                if words[j] in self.negation_words:
                    has_negation = True
                    break

            # Check for intensifiers
            intensifier = 1.0
            if i > 0 and words[i - 1] in self.intensifiers:
                intensifier = self.intensifiers[words[i - 1]]

            # Check positive keywords
            if word in self.positive_keywords:
                score = self.positive_keywords[word] * intensifier
                if has_negation:
                    score = -score * 0.7  # Negation flips and reduces
                total_score += score
                matched.append({
                    "keyword": word,
                    "base_score": self.positive_keywords[word],
                    "final_score": score,
                    "negated": has_negation
                })

            # Check negative keywords
            elif word in self.negative_keywords:
                score = self.negative_keywords[word] * intensifier
                if has_negation:
                    score = -score * 0.5  # Negation flips but reduced
                total_score += score
                matched.append({
                    "keyword": word,
                    "base_score": self.negative_keywords[word],
                    "final_score": score,
                    "negated": has_negation
                })

        # Normalize by number of sentiment words (with diminishing returns)
        if matched:
            avg_score = total_score / (len(matched) ** 0.5)
            # Clamp to -1 to 1
            final_score = max(-1.0, min(1.0, avg_score))
        else:
            final_score = 0.0

        return final_score, matched

    def _detect_emotion(self, words: List[str]) -> Tuple[str, Dict[str, float]]:
        """Detect primary emotion from text"""
        emotion_counts = {emotion: 0 for emotion in self.emotion_keywords}

        for word in words:
            for emotion, keywords in self.emotion_keywords.items():
                if word in keywords:
                    emotion_counts[emotion] += 1

        # Normalize scores
        total = sum(emotion_counts.values()) or 1
        emotion_scores = {k: v / total for k, v in emotion_counts.items()}

        # Get primary emotion
        primary_emotion = max(emotion_counts, key=emotion_counts.get)
        if emotion_counts[primary_emotion] == 0:
            primary_emotion = "neutral"

        return primary_emotion, emotion_scores

    def _analyze_aspects(self, text: str) -> Dict[str, Dict[str, Any]]:
        """Analyze sentiment by aspect"""
        aspect_sentiments = {}

        for aspect, keywords in self.aspects.items():
            # Check if aspect is mentioned
            aspect_mentioned = any(kw in text for kw in keywords)

            if aspect_mentioned:
                # Find relevant context around aspect keywords
                aspect_score = 0.0
                mentions = 0

                for kw in keywords:
                    if kw in text:
                        mentions += 1
                        # Simple context-based scoring
                        for pos_word, score in self.positive_keywords.items():
                            if pos_word in text:
                                # Check proximity (simple approach)
                                aspect_score += score * 0.5

                        for neg_word, score in self.negative_keywords.items():
                            if neg_word in text:
                                aspect_score += score * 0.5

                if mentions > 0:
                    aspect_sentiments[aspect] = {
                        "sentiment": round(max(-1, min(1, aspect_score / mentions)), 2),
                        "mentions": mentions,
                        "label": "positive" if aspect_score > 0.1 else "negative" if aspect_score < -0.1 else "neutral"
                    }

        return aspect_sentiments

    def _detect_triggers(
        self,
        text: str,
        matched_keywords: List[Dict],
        aspect_sentiments: Dict
    ) -> List[Dict[str, Any]]:
        """Detect what triggered the sentiment"""
        triggers = []

        # Aspect-based triggers
        for aspect, data in aspect_sentiments.items():
            if data["label"] != "neutral":
                triggers.append({
                    "aspect": aspect,
                    "sentiment": data["label"],
                    "type": "aspect"
                })

        # Keyword-based triggers
        strong_keywords = [kw for kw in matched_keywords if abs(kw.get("final_score", 0)) >= 0.7]
        for kw in strong_keywords[:3]:
            sentiment_type = "positive" if kw["final_score"] > 0 else "negative"
            triggers.append({
                "keyword": kw["keyword"],
                "sentiment": sentiment_type,
                "type": "keyword"
            })

        return triggers[:5]

    def _get_sentiment_label(self, score: float) -> str:
        """Convert score to label"""
        if score >= 0.5:
            return "very_positive"
        elif score >= 0.2:
            return "positive"
        elif score >= -0.2:
            return "neutral"
        elif score >= -0.5:
            return "negative"
        else:
            return "very_negative"

    def _calculate_confidence(self, matched_keywords: List, word_count: int) -> float:
        """Calculate confidence in the analysis"""
        if word_count == 0:
            return 0.0

        # Base confidence on keyword coverage
        keyword_ratio = len(matched_keywords) / max(word_count, 1)
        base_confidence = min(0.5 + keyword_ratio * 2, 0.9)

        # Adjust for text length (longer text = more reliable)
        if word_count >= 50:
            length_bonus = 0.1
        elif word_count >= 20:
            length_bonus = 0.05
        else:
            length_bonus = 0.0

        return min(0.95, base_confidence + length_bonus)

    def _generate_summary(
        self,
        sentiment_label: str,
        primary_emotion: str,
        triggers: List,
        aspect_sentiments: Dict
    ) -> str:
        """Generate human-readable summary"""
        sentiment_text = sentiment_label.replace("_", " ")

        # Build summary
        if sentiment_label in ["very_positive", "positive"]:
            summary = f"Guest expressed {sentiment_text} sentiment"
        elif sentiment_label in ["very_negative", "negative"]:
            summary = f"Guest expressed {sentiment_text} sentiment - attention recommended"
        else:
            summary = "Guest sentiment is neutral"

        # Add emotion context
        if primary_emotion != "neutral":
            summary += f", primarily {primary_emotion}"

        # Add aspect highlights
        negative_aspects = [k for k, v in aspect_sentiments.items() if v["label"] == "negative"]
        if negative_aspects:
            summary += f". Concerns about: {', '.join(negative_aspects)}"

        return summary

    def _empty_result(self) -> Dict[str, Any]:
        """Return empty result for invalid input"""
        return {
            "sentiment_score": 0.0,
            "sentiment_label": "neutral",
            "primary_emotion": "neutral",
            "emotion_scores": {},
            "emotion_intensity": 0.0,
            "aspect_sentiments": {},
            "triggers": [],
            "matched_keywords": [],
            "confidence": 0.0,
            "source": "unknown",
            "text_length": 0,
            "word_count": 0,
            "model_version": self.model_version,
            "analysis_summary": "No text provided for analysis",
        }

    def analyze_batch(self, texts: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Analyze multiple texts"""
        results = []
        for item in texts:
            text = item.get("text", "")
            source = item.get("source", "feedback")
            results.append(self.analyze(text, source))
        return results

    def get_sentiment_trend(self, analyses: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Calculate sentiment trend from multiple analyses"""
        if not analyses:
            return {"trend": "stable", "change": 0.0, "data_points": 0}

        scores = [a.get("sentiment_score", 0) for a in analyses]

        if len(scores) < 2:
            return {"trend": "stable", "change": 0.0, "data_points": len(scores)}

        # Simple trend calculation
        first_half = sum(scores[:len(scores)//2]) / (len(scores)//2)
        second_half = sum(scores[len(scores)//2:]) / (len(scores) - len(scores)//2)
        change = second_half - first_half

        if change > 0.2:
            trend = "improving"
        elif change < -0.2:
            trend = "declining"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "change": round(change, 3),
            "average_score": round(sum(scores) / len(scores), 3),
            "data_points": len(scores),
            "latest_score": scores[-1] if scores else 0
        }
