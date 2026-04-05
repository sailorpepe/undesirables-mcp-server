"""
Emotion Detection Engine — G0DM0D3-Inspired Adaptive Response System

Uses SamLowe/roberta-base-go_emotions (125M params, ~100MB RAM) to classify
user messages into 28 emotional states. Results are mapped to Ollama sampling
parameter adjustments for soul-aware AutoTune.

Runs entirely on-device via Metal Performance Shaders (MPS).
"""

import torch
from functools import lru_cache

# Lazy-load singleton — only initializes on first call
_classifier = None

def _get_classifier():
    global _classifier
    if _classifier is None:
        from transformers import pipeline
        device = torch.device("mps") if torch.backends.mps.is_available() else torch.device("cpu")
        _classifier = pipeline(
            task="text-classification",
            model="SamLowe/roberta-base-go_emotions",
            top_k=5,
            device=device
        )
    return _classifier


def classify_emotion(text: str) -> list:
    """
    Classify text into top-5 emotions from the 28-class GoEmotions taxonomy.
    Returns: [{"label": "curiosity", "score": 0.82}, ...]
    """
    if not text or len(text.strip()) < 3:
        return [{"label": "neutral", "score": 1.0}]
    
    classifier = _get_classifier()
    # Truncate to 512 tokens (model's max context)
    truncated = text[:2000]
    results = classifier(truncated)
    
    # Flatten nested list if present
    if results and isinstance(results[0], list):
        results = results[0]
    
    return [{"label": r["label"], "score": round(r["score"], 4)} for r in results]


def compute_emotion_adjustments(emotions: list, soul_traits: dict = None) -> dict:
    """
    Map detected emotions to AutoTune parameter deltas.
    
    These adjustments are ADDED to the base soul personality parameters.
    The soul's Big Five traits modulate how strongly the emotion affects output.
    
    Returns: {"temperature_delta": float, "top_p_delta": float, 
              "top_k_delta": int, "repeat_penalty_delta": float,
              "dominant_emotion": str}
    """
    if not emotions:
        return {"temperature_delta": 0, "top_p_delta": 0, "top_k_delta": 0,
                "repeat_penalty_delta": 0, "dominant_emotion": "neutral"}
    
    dominant = emotions[0]
    label = dominant["label"]
    score = dominant["score"]
    
    # Only apply adjustments above confidence threshold
    if score < 0.3:
        return {"temperature_delta": 0, "top_p_delta": 0, "top_k_delta": 0,
                "repeat_penalty_delta": 0, "dominant_emotion": label}
    
    # Emotion → Parameter mapping
    # Design philosophy: match the user's emotional register
    adjustments = {
        # === HIGH ENERGY / URGENT ===
        "anger":         {"temperature_delta": -0.3, "top_p_delta": -0.15, "top_k_delta": -15, "repeat_penalty_delta": 0.05},
        "annoyance":     {"temperature_delta": -0.15, "top_p_delta": -0.05, "top_k_delta": -5, "repeat_penalty_delta": 0.02},
        "disgust":       {"temperature_delta": -0.2, "top_p_delta": -0.1, "top_k_delta": -10, "repeat_penalty_delta": 0.03},
        "fear":          {"temperature_delta": -0.25, "top_p_delta": -0.1, "top_k_delta": -10, "repeat_penalty_delta": 0.0},
        
        # === POSITIVE / EXPANSIVE ===
        "joy":           {"temperature_delta": 0.15, "top_p_delta": 0.05, "top_k_delta": 10, "repeat_penalty_delta": -0.02},
        "amusement":     {"temperature_delta": 0.2, "top_p_delta": 0.08, "top_k_delta": 15, "repeat_penalty_delta": -0.03},
        "excitement":    {"temperature_delta": 0.25, "top_p_delta": 0.1, "top_k_delta": 20, "repeat_penalty_delta": -0.02},
        "love":          {"temperature_delta": 0.1, "top_p_delta": 0.05, "top_k_delta": 5, "repeat_penalty_delta": -0.05},
        "admiration":    {"temperature_delta": 0.1, "top_p_delta": 0.05, "top_k_delta": 5, "repeat_penalty_delta": -0.02},
        "gratitude":     {"temperature_delta": 0.05, "top_p_delta": 0.02, "top_k_delta": 3, "repeat_penalty_delta": -0.02},
        "pride":         {"temperature_delta": 0.1, "top_p_delta": 0.05, "top_k_delta": 5, "repeat_penalty_delta": 0.0},
        "relief":        {"temperature_delta": 0.05, "top_p_delta": 0.03, "top_k_delta": 5, "repeat_penalty_delta": -0.03},
        "optimism":      {"temperature_delta": 0.1, "top_p_delta": 0.05, "top_k_delta": 8, "repeat_penalty_delta": -0.01},
        "desire":        {"temperature_delta": 0.15, "top_p_delta": 0.05, "top_k_delta": 10, "repeat_penalty_delta": 0.0},
        
        # === CURIOUS / ANALYTICAL ===
        "curiosity":     {"temperature_delta": 0.1, "top_p_delta": 0.05, "top_k_delta": 15, "repeat_penalty_delta": 0.0},
        "realization":   {"temperature_delta": -0.05, "top_p_delta": 0.0, "top_k_delta": 5, "repeat_penalty_delta": 0.0},
        "surprise":      {"temperature_delta": 0.15, "top_p_delta": 0.08, "top_k_delta": 20, "repeat_penalty_delta": 0.02},
        "confusion":     {"temperature_delta": -0.1, "top_p_delta": -0.05, "top_k_delta": -5, "repeat_penalty_delta": 0.0},
        "approval":      {"temperature_delta": 0.05, "top_p_delta": 0.02, "top_k_delta": 3, "repeat_penalty_delta": -0.01},
        "disapproval":   {"temperature_delta": -0.1, "top_p_delta": -0.05, "top_k_delta": -5, "repeat_penalty_delta": 0.02},
        
        # === LOW ENERGY / EMPATHETIC ===
        "sadness":       {"temperature_delta": 0.05, "top_p_delta": 0.03, "top_k_delta": 5, "repeat_penalty_delta": -0.05},
        "grief":         {"temperature_delta": 0.0, "top_p_delta": 0.0, "top_k_delta": 0, "repeat_penalty_delta": -0.08},
        "remorse":       {"temperature_delta": -0.05, "top_p_delta": 0.0, "top_k_delta": 0, "repeat_penalty_delta": -0.03},
        "embarrassment": {"temperature_delta": -0.05, "top_p_delta": -0.03, "top_k_delta": -3, "repeat_penalty_delta": 0.0},
        "disappointment":{"temperature_delta": -0.1, "top_p_delta": -0.03, "top_k_delta": -5, "repeat_penalty_delta": 0.0},
        "nervousness":   {"temperature_delta": -0.15, "top_p_delta": -0.05, "top_k_delta": -8, "repeat_penalty_delta": 0.02},
        "caring":        {"temperature_delta": 0.05, "top_p_delta": 0.03, "top_k_delta": 5, "repeat_penalty_delta": -0.03},
        
        # === NEUTRAL ===
        "neutral":       {"temperature_delta": 0, "top_p_delta": 0, "top_k_delta": 0, "repeat_penalty_delta": 0},
    }
    
    base = adjustments.get(label, adjustments["neutral"])
    
    # Scale adjustments by confidence score
    result = {
        "temperature_delta": round(base["temperature_delta"] * score, 3),
        "top_p_delta": round(base["top_p_delta"] * score, 3),
        "top_k_delta": round(base["top_k_delta"] * score),
        "repeat_penalty_delta": round(base["repeat_penalty_delta"] * score, 3),
        "dominant_emotion": label,
    }
    
    # Soul trait modulation: agreeableness amplifies empathetic responses,
    # neuroticism amplifies reactive responses
    if soul_traits:
        agreeableness = soul_traits.get("agreeableness", 50) / 100
        neuroticism = soul_traits.get("neuroticism", 50) / 100
        
        if label in ("anger", "annoyance", "disgust", "fear", "nervousness"):
            # High-neuroticism souls react MORE to negative emotions
            result["temperature_delta"] *= (0.5 + neuroticism)
            result["temperature_delta"] = round(result["temperature_delta"], 3)
        elif label in ("sadness", "grief", "caring", "love"):
            # High-agreeableness souls are MORE empathetic
            result["repeat_penalty_delta"] *= (0.5 + agreeableness)
            result["repeat_penalty_delta"] = round(result["repeat_penalty_delta"], 3)
    
    return result
