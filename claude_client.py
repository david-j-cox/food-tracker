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


def generate_initial_questions(
    image_bytes: bytes, media_type: str = "image/jpeg"
) -> list[dict]:
    """Look at a food photo and generate questions to understand it before identification.

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
                        "text": """Look at this food photo. Before trying to identify it or estimate nutrition, I need to gather information from the person who took the photo.

Generate 3-5 short, targeted questions that would help you understand what this food is and estimate its nutritional content accurately. Tailor the questions to what you see — for example:
- Ask them to describe the food in their own words
- Ask about portion size / how much is shown
- Ask whether it's from a restaurant or homemade, and if from a restaurant, which one
- Ask about preparation method or key ingredients if not obvious from the photo
- Ask about any other details that would significantly affect the nutritional estimate

Return a JSON array where each element has:
{
  "question": "short question text",
  "options": ["option1", "option2", "option3"] or null
}

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


def identify_from_answers(
    image_bytes: bytes,
    qa_pairs: list[dict],
    media_type: str = "image/jpeg",
) -> dict:
    """Identify food and generate a search term from photo + user's answers.

    Returns dict with keys: food_name, search_term, restaurant (or None).
    """
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    qa_text = "\n".join(
        f"Q: {qa['question']}\nA: {qa['answer']}" for qa in qa_pairs
    )

    message = client.messages.create(
        model=MODEL,
        max_tokens=512,
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
                        "text": f"""Based on this photo and the user's answers below, identify this food.

{qa_text}

Return a JSON object with exactly these keys:
{{
  "food_name": "descriptive name of the food (e.g. 'Grilled chicken breast with steamed broccoli')",
  "search_term": "simplified USDA search term for the primary food item (e.g. 'chicken breast grilled')",
  "restaurant": "restaurant name if the user mentioned one, otherwise null"
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


def search_web_nutrition(food_name: str, restaurant: str | None = None) -> dict:
    """Search the web for nutrition information when USDA has no match.

    Uses Claude's built-in web search tool to find nutrition data from
    restaurant websites, recipe sites, etc.

    Returns dict with keys: source_url, source_name, serving_size, nutrients.
    """
    search_context = f'"{food_name}"'
    if restaurant:
        search_context = f'"{food_name}" from {restaurant}'

    message = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 3}],
        messages=[
            {
                "role": "user",
                "content": f"""Search the web for nutrition information for {search_context}.

Look for calorie counts, macronutrients (protein, fat, carbs), and any other nutritional details you can find from reliable sources like restaurant websites, MyFitnessPal, Nutritionix, CalorieKing, or similar.

Return a JSON object with these keys:
{{
  "source_url": "URL where you found the information, or null",
  "source_name": "name of the source (e.g. 'McDonald's website', 'MyFitnessPal'), or null",
  "serving_size": "serving size if found, or null",
  "nutrients": {{
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
  }}
}}

If you cannot find reliable nutrition information, return {{"source_url": null, "source_name": null, "serving_size": null, "nutrients": {{}}}}.
Return ONLY the JSON object, no other text.""",
            }
        ],
    )

    # With server-side tools, extract the final text block
    text = ""
    for block in message.content:
        if block.type == "text":
            text = block.text.strip()

    if not text:
        return {"source_url": None, "source_name": None, "serving_size": None, "nutrients": {}}

    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

    return json.loads(text)


def estimate_with_context(
    image_bytes: bytes,
    media_type: str,
    qa_pairs: list[dict],
    food_name: str,
    usda_nutrients: dict | None = None,
    web_nutrition: dict | None = None,
    restaurant: str | None = None,
) -> dict:
    """Produce final nutrient estimate using all available context.

    Returns dict with keys: food_name, estimated_serving_size, data_source,
    estimated_nutrients, suggested_tags.
    """
    image_b64 = base64.standard_b64encode(image_bytes).decode("utf-8")

    qa_text = "\n".join(
        f"Q: {qa['question']}\nA: {qa['answer']}" for qa in qa_pairs
    )

    context_parts = [
        f"The user described this food as: {food_name}",
        f"\nUser's answers to clarifying questions:\n{qa_text}",
    ]
    if restaurant:
        context_parts.append(f"\nThis is from: {restaurant}")
    if usda_nutrients:
        context_parts.append(
            f"\nUSDA database nutrients (per serving): {json.dumps(usda_nutrients)}"
        )
    if web_nutrition and web_nutrition.get("nutrients"):
        source = web_nutrition.get("source_name", "web search")
        context_parts.append(
            f"\nNutrition info found online ({source}): {json.dumps(web_nutrition)}"
        )

    context = "\n".join(context_parts)

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
                        "text": f"""Using the photo and all the context below, provide your best estimate of the nutritional content of this food.

{context}

Cross-reference the photo with any external data provided. Adjust for the actual portion size visible in the photo.

Return a JSON object with exactly these keys:
{{
  "food_name": "refined descriptive name",
  "estimated_serving_size": "estimated portion size shown in the photo",
  "data_source": "where the nutrient data primarily came from (e.g. 'USDA', 'restaurant website', 'Claude estimate')",
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
