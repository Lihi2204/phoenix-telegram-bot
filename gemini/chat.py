"""Gemini chat with File Search for Phoenix Telegram Bot."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

from google import genai
from google.genai import types


class GeminiChat:
    """Query Gemini with File Search for insurance questions."""

    SYSTEM_PROMPT = """
אתה יועץ ביטוח מקצועי שעוזר ללקוחות להבין את פוליסות ביטוח הבריאות שלהם מחברת פניקס.

הנחיות:
1. ענה בעברית תמיד
2. התבסס אך ורק על המידע מהמסמכים - אל תמציא מידע
3. אם המידע לא נמצא במסמכים, אמור זאת בבירור
4. הסבר מונחים מקצועיים בשפה פשוטה וברורה
5. כאשר אתה מצטט מידע, ציין את שם הפוליסה או הנספח הרלוונטי
6. אם יש תנאים מוקדמים לכיסוי (כגון אישור רופא, תקופת אכשרה), ציין אותם
7. אם יש ספק או המידע לא ברור, המלץ לפנות לסוכן הביטוח לבירור
8. היה מדויק בנוגע לסכומים, אחוזים ותנאים
9. אם השאלה לא קשורה לביטוח בריאות, הסבר בנימוס שאתה יכול לעזור רק בנושאי ביטוח

דוגמאות לתשובות טובות:
- "לפי פוליסת הבריאות שלך, יש לך כיסוי לריפוי בעיסוק עד 50 טיפולים בשנה, עם השתתפות עצמית של 50 ש״ח לטיפול."
- "לא מצאתי במסמכים מידע על כיסוי לטיפול ספציפי זה. מומלץ לפנות לסוכן הביטוח שלך לבירור."
"""

    def __init__(self, api_key: str, model: str = "gemini-3-pro"):
        """
        Initialize Gemini chat client.

        Args:
            api_key: Google Gemini API key
            model: Model name to use (default: gemini-3-pro)
        """
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self._executor = ThreadPoolExecutor(max_workers=2)

    async def _run_sync(self, func, *args, **kwargs):
        """Run synchronous SDK call in thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            lambda: func(*args, **kwargs)
        )

    async def query(self, question: str, store_name: str) -> str:
        """
        Query Gemini about insurance documents.

        Args:
            question: User's question in Hebrew
            store_name: File Search store name containing user's documents

        Returns:
            Hebrew response text
        """
        import logging
        logger = logging.getLogger(__name__)

        try:
            logger.info(f"Querying Gemini with store: {store_name}")
            logger.info(f"Question: {question}")

            response = await self._run_sync(
                self.client.models.generate_content,
                model=self.model,
                contents=[
                    {"role": "user", "parts": [{"text": self.SYSTEM_PROMPT}]},
                    {"role": "model", "parts": [{"text": "הבנתי. אני מוכן לענות על שאלות לגבי פוליסות ביטוח הבריאות שלך מחברת פניקס. אתבסס רק על המידע מהמסמכים שלך."}]},
                    {"role": "user", "parts": [{"text": question}]}
                ],
                config=types.GenerateContentConfig(
                    tools=[
                        types.Tool(
                            file_search=types.FileSearch(
                                file_search_store_names=[store_name]
                            )
                        )
                    ]
                )
            )

            logger.info(f"Gemini response candidates: {len(response.candidates) if response.candidates else 0}")

            # Check if file search was used
            if response.candidates and response.candidates[0].grounding_metadata:
                logger.info(f"Grounding metadata: {response.candidates[0].grounding_metadata}")

            if response.text:
                logger.info(f"Response length: {len(response.text)}")
                return response.text
            else:
                logger.warning("No text in Gemini response")
                return "לא הצלחתי למצוא תשובה במסמכים. נסה לנסח את השאלה אחרת."

        except Exception as e:
            logger.error(f"Gemini query error: {e}", exc_info=True)
            return "אירעה שגיאה בעת חיפוש התשובה. נא לנסות שוב."

    async def query_with_context(
        self,
        question: str,
        store_name: str,
        conversation_history: Optional[list] = None
    ) -> str:
        """
        Query Gemini with conversation history context.

        Args:
            question: User's current question
            store_name: File Search store name
            conversation_history: Optional list of previous (question, answer) tuples

        Returns:
            Hebrew response text
        """
        try:
            # Build conversation with history
            contents = [
                {"role": "user", "parts": [{"text": self.SYSTEM_PROMPT}]},
                {"role": "model", "parts": [{"text": "הבנתי. אני מוכן לענות על שאלות לגבי פוליסות ביטוח הבריאות שלך."}]}
            ]

            # Add conversation history if provided
            if conversation_history:
                for prev_question, prev_answer in conversation_history[-5:]:  # Last 5 exchanges
                    contents.append({"role": "user", "parts": [{"text": prev_question}]})
                    contents.append({"role": "model", "parts": [{"text": prev_answer}]})

            # Add current question
            contents.append({"role": "user", "parts": [{"text": question}]})

            response = await self._run_sync(
                self.client.models.generate_content,
                model=self.model,
                contents=contents,
                config=types.GenerateContentConfig(
                    tools=[
                        types.Tool(
                            file_search=types.FileSearch(
                                file_search_store_names=[store_name]
                            )
                        )
                    ]
                )
            )

            if response.text:
                return response.text
            else:
                return "לא הצלחתי למצוא תשובה במסמכים. נסה לנסח את השאלה אחרת."

        except Exception as e:
            print(f"Gemini query error: {e}")
            return "אירעה שגיאה בעת חיפוש התשובה. נא לנסות שוב."

    def close(self):
        """Cleanup resources."""
        self._executor.shutdown(wait=False)
