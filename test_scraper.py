"""Test script for Phoenix scraper - run manually to debug."""

import asyncio
from pathlib import Path
from scraper.phoenix_downloader import PhoenixDownloader
from scraper.progress_callback import ProgressStage


async def progress_callback(stage, message=None, current=None, total=None, error=None):
    """Print progress to console."""
    print(f"[{stage.value}] {message or ''} {f'{current}/{total}' if current else ''}")
    if error:
        print(f"  ERROR: {error}")


async def test_login():
    """Test the login flow interactively."""
    print("=" * 50)
    print("Phoenix Insurance Scraper Test")
    print("=" * 50)

    # Get credentials from user
    user_id = input("Enter Israeli ID (9 digits): ").strip()
    phone = input("Enter phone (05XXXXXXXX): ").strip()

    download_dir = Path("test_download")
    download_dir.mkdir(exist_ok=True)

    print("\nStarting browser...")

    async with PhoenixDownloader(
        user_id=user_id,
        phone=phone,
        download_dir=download_dir,
        progress_callback=progress_callback,
        headless=False  # Show browser for debugging
    ) as scraper:

        print("\nInitiating login (sending OTP)...")
        success = await scraper.initiate_login()

        if not success:
            print("ERROR: Failed to initiate login!")
            print("Check if the Phoenix website has changed.")
            input("Press Enter to close browser...")
            return

        print("\nOTP should be sent to your phone!")
        otp = input("Enter OTP code (6 digits): ").strip()

        print("\nCompleting login...")
        success = await scraper.complete_login(otp)

        if not success:
            print("ERROR: Login failed! OTP may be wrong or expired.")
            input("Press Enter to close browser...")
            return

        print("\nLogin successful! Downloading documents...")
        pdf_paths = await scraper.download_health_documents()

        print(f"\nDownloaded {len(pdf_paths)} files:")
        for path in pdf_paths:
            print(f"  - {path}")

        input("\nPress Enter to close browser...")


if __name__ == "__main__":
    asyncio.run(test_login())
