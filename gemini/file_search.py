"""Gemini File Search store management for Phoenix Telegram Bot."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, List, Callable, Awaitable

from google import genai
from google.genai import types


class GeminiFileSearch:
    """Manages Gemini File Search stores for user documents."""

    def __init__(self, api_key: str):
        """
        Initialize Gemini File Search client.

        Args:
            api_key: Google Gemini API key
        """
        self.client = genai.Client(api_key=api_key)
        self._executor = ThreadPoolExecutor(max_workers=3)

    async def _run_sync(self, func, *args, **kwargs):
        """Run synchronous SDK call in thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            self._executor,
            lambda: func(*args, **kwargs)
        )

    async def create_store(self, user_id: int) -> str:
        """
        Create a new File Search store for a user.

        Args:
            user_id: Telegram user ID for unique naming

        Returns:
            Store name (resource ID)
        """
        store = await self._run_sync(
            self.client.file_search_stores.create,
            config={'display_name': f'phoenix_user_{user_id}'}
        )
        return store.name

    async def delete_store(self, store_name: str) -> bool:
        """
        Delete a File Search store.

        Args:
            store_name: Store resource name to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            await self._run_sync(
                self.client.file_search_stores.delete,
                name=store_name
            )
            return True
        except Exception as e:
            print(f"Error deleting store {store_name}: {e}")
            return False

    async def upload_documents(
        self,
        store_name: str,
        pdf_paths: List[Path],
        progress_callback: Optional[Callable[[int, int], Awaitable[None]]] = None
    ) -> int:
        """
        Upload PDF documents to a File Search store.

        Args:
            store_name: Target store name
            pdf_paths: List of PDF file paths to upload
            progress_callback: Optional async callback(current, total) for progress updates

        Returns:
            Count of successfully uploaded files
        """
        import time
        import shutil
        import tempfile
        import re

        uploaded = 0
        total = len(pdf_paths)

        # Create temp directory for renamed files
        temp_dir = Path(tempfile.mkdtemp(prefix="phoenix_upload_"))

        try:
            for i, pdf_path in enumerate(pdf_paths):
                try:
                    # Create ASCII-safe filename
                    # Extract meaningful parts and transliterate or use index
                    original_name = pdf_path.name

                    # Try to extract the appendix number (e.g., "נספח_5420")
                    appendix_match = re.search(r'(\d{4,5})', original_name)
                    appendix_num = appendix_match.group(1) if appendix_match else ""

                    # Create safe filename with index
                    safe_name = f"doc_{i+1:03d}_{appendix_num}.pdf" if appendix_num else f"doc_{i+1:03d}.pdf"

                    # Copy file to temp with safe name
                    temp_path = temp_dir / safe_name
                    shutil.copy2(pdf_path, temp_path)

                    # Upload file to store using the temp path
                    operation = await self._run_sync(
                        self.client.file_search_stores.upload_to_file_search_store,
                        file=str(temp_path),
                        file_search_store_name=store_name,
                        config={'display_name': safe_name}
                    )

                    # Wait for upload to complete if it's an operation
                    if hasattr(operation, 'done'):
                        while not operation.done:
                            await asyncio.sleep(1)
                            operation = await self._run_sync(
                                self.client.operations.get,
                                operation
                            )

                    uploaded += 1

                    if progress_callback:
                        await progress_callback(i + 1, total)

                except Exception as e:
                    # Log error but continue with other files
                    print(f"Failed to upload {pdf_path.name}: {e}")

        finally:
            # Cleanup temp directory
            try:
                shutil.rmtree(temp_dir)
            except Exception:
                pass

        return uploaded

    async def get_store_info(self, store_name: str) -> Optional[dict]:
        """
        Get information about a File Search store.

        Args:
            store_name: Store resource name

        Returns:
            Dict with store info or None if not found
        """
        try:
            store = await self._run_sync(
                self.client.file_search_stores.get,
                name=store_name
            )
            return {
                'name': store.name,
                'display_name': store.display_name,
            }
        except Exception as e:
            print(f"Error getting store info: {e}")
            return None

    async def list_store_files(self, store_name: str) -> List[dict]:
        """
        List files in a File Search store.

        Args:
            store_name: Store resource name

        Returns:
            List of file info dicts
        """
        try:
            # Note: This may need adjustment based on actual API
            files = await self._run_sync(
                self.client.file_search_stores.list_files,
                file_search_store_name=store_name
            )
            return [{'name': f.name, 'display_name': f.display_name} for f in files]
        except Exception as e:
            print(f"Error listing store files: {e}")
            return []

    def close(self):
        """Cleanup resources."""
        self._executor.shutdown(wait=False)
