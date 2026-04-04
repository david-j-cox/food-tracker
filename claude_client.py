"""Claude Vision API client for food identification and nutrition label extraction."""

import base64
import json

import anthropic

from config import Config

client = anthropic.Anthropic(api_key=Config.ANTHROPIC_API_KEY)
MODEL = "claude-sonnet-4-6"


def identify_food(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Identify food from a photo and estimate nutrients.

    Returns dict with keys:
        food_name: str - identified food name
        search_term: str - simplified term for USDA search
        estimated_nutrients: dict - rough nutrient estimates per serving
    """
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": """Identify the food in this image. Return a JSON object with exactly these keys:

{
  "food_name": "descriptive name of the food (e.g. 'Grilled chicken breast with steamed broccoli')",
  "search_term": "simplified USDA search term for the primary food item (e.g. 'chicken breast grilled')",
  "estimated_serving_size": "estimate of the portion shown (e.g. '6 oz', '1.5 cups', '2 slices')",
  "estimated_nutrients": {
    "calories": number or null,
    "total_fat_g": number or null,
    "saturated_fat_g": number or null,
    "protein_g": number or null,
    "carbohydrates_g": number or null,
    "fiber_g": number or null,
    "sugar_g": number or null,
    "sodium_mg": number or null,
    "iron_mg": number or null,
    "calcium_mg": number or null,
    "magnesium_mg": number or null,
    "potassium_mg": number or null,
    "vitamin_b12_mcg": number or null,
    "vitamin_d_mcg": number or null
  },
  "suggested_tags": ["tag1", "tag2"]
}

Estimate nutrients per serving based on the apparent portion size.
For suggested_tags, use terms like: high-fat, fried, dairy, spicy, raw, fermented, processed, whole-food, omega-3-rich, caffeine, alcohol, hydration.
Return ONLY the JSON object, no other text.""",
                    },
                ],
            }
        ],
    )

    text = message.content[0].text.strip()
    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    return json.loads(text)


def extract_label(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """Extract nutrient values from a nutrition label photo.

    Returns dict with keys:
        food_name: str - product name if visible
        brand: str or None
        nutrients: dict - extracted nutrient values
    """
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": """Extract the nutrition information from this nutrition label. Return a JSON object with exactly these keys:

{
  "food_name": "product name if visible, otherwise 'Unknown Product'",
  "brand": "brand name if visible, otherwise null",
  "serving_size": "serving size as shown on label",
  "nutrients": {
    "calories": number or null,
    "total_fat_g": number or null,
    "saturated_fat_g": number or null,
    "protein_g": number or null,
    "carbohydrates_g": number or null,
    "fiber_g": number or null,
    "sugar_g": number or null,
    "sodium_mg": number or null,
    "iron_mg": number or null,
    "calcium_mg": number or null,
    "magnesium_mg": number or null,
    "potassium_mg": number or null,
    "vitamin_b12_mcg": number or null,
    "vitamin_d_mcg": number or null
  },
  "suggested_tags": ["tag1", "tag2"]
}

Extract exact values from the label. Convert percentages to absolute values where possible using standard daily values.
For nutrients not listed on the label, use null.
Return ONLY the JSON object, no other text.""",
                    },
                ],
            }
        ],
    )

    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    return json.loads(text)


def generate_clarifying_questions(
    food_name: str, image_bytes: bytes, media_type: str = "image/jpeg"
) -> list[dict]:
    """Generate targeted questions to pin down the exact food variant.

    Returns a list of dicts, each with:
        question: str - the question text
        options: list[str] or None - suggested answers (None = free text)
    """
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": f"""You identified this food as "{food_name}". I need to estimate its nutritional content accurately, but similar-looking foods can vary wildly (e.g. Greek yogurt vs regular yogurt, whole milk vs skim, fried vs baked).

Generate 3-5 short, targeted questions that would most impact the nutritional estimate. Focus on:
- Specific variant/type (e.g. Greek vs regular, whole wheat vs white)
- Fat content or preparation method (e.g. fried, baked, grilled, raw)
- Key ingredients or additions (e.g. added sugar, oil, cheese, dressing)
- Portion size clarification if ambiguous from the photo

Return a JSON array where each element has:
{{
  "question": "short question text",
  "options": ["option1", "option2", "option3"] or null
}}

Use "options" for questions with a small set of likely answers (2-5 options).
Use null for open-ended questions where options don't make sense.
Return ONLY the JSON array, no other text.""",
                    },
                ],
            }
        ],
    )

    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    return json.loads(text)


def refine_estimate(
    food_name: str,
    questions_and_answers: list[dict],
    image_bytes: bytes,
    media_type: str = "image/jpeg",
) -> dict:
    """Re-estimate nutrients using clarifying answers from the user.

    questions_and_answers: list of {"question": str, "answer": str}

    Returns dict with same structure as identify_food()'s estimated_nutrients,
    plus estimated_serving_size.
    """
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    qa_text = "\n".join(
        f"Q: {qa['question']}\nA: {qa['answer']}" for qa in questions_and_answers
    )

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_b64,
                        },
                    },
                    {
                        "type": "text",
                        "text": f"""You identified this food as "{food_name}". The user answered these clarifying questions:

{qa_text}

Using the photo AND the user's answers, provide your best nutrient estimate. Be as specific as possible given what you now know about the exact food variant, preparation method, and portion.

Return a JSON object with exactly these keys:
{{
  "food_name": "refined descriptive name incorporating what you learned (e.g. 'Non-fat Greek yogurt with honey')",
  "estimated_serving_size": "estimated portion size (e.g. '6 oz', '1.5 cups')",
  "estimated_nutrients": {{
    "calories": number or null,
    "total_fat_g": number or null,
    "saturated_fat_g": number or null,
    "protein_g": number or null,
    "carbohydrates_g": number or null,
    "fiber_g": number or null,
    "sugar_g": number or null,
    "sodium_mg": number or null,
    "iron_mg": number or null,
    "calcium_mg": number or null,
    "magnesium_mg": number or null,
    "potassium_mg": number or null,
    "vitamin_b12_mcg": number or null,
    "vitamin_d_mcg": number or null
  }},
  "suggested_tags": ["tag1", "tag2"]
}}

Return ONLY the JSON object, no other text.""",
                    },
                ],
            }
        ],
    )

    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    return json.loads(text)


def describe_serving_size(food_name: str, serving_size: str) -> str:
    """Convert a technical serving size into an everyday visual reference.

    Takes something like "156g" and returns something like
    "156g (~2 handfuls, half a standard bowl)".
    """
    message = client.messages.create(
        model=MODEL,
        max_tokens=100,
        messages=[
            {
                "role": "user",
                "content": f"""For the food "{food_name}", the standard serving size is {serving_size}.

Rewrite this as a short, practical reference that someone could eyeball without a scale. Include the original measurement plus an everyday comparison.

Examples of good responses:
- "172g (~size of your palm, or a deck of cards)"
- "1 cup / 156g (~a baseball, fills half a soup bowl)"
- "2 tbsp / 32g (~a golf ball)"
- "85g (~size of a checkbook, 1/4 of a dinner plate)"

Return ONLY the description, no other text. Keep it under 80 characters.""",
            }
        ],
    )
    return message.content[0].text.strip()
