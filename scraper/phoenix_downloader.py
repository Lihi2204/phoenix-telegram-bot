"""
Phoenix Insurance Document Downloader.

Async Playwright-based scraper for downloading health insurance policies
from Phoenix Insurance (my.fnx.co.il) personal portal.

Based on: https://github.com/Lihi2204/phoenix-insurance-scraper
"""

import asyncio
import re
from pathlib import Path
from typing import Optional, List
from datetime import datetime

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
    Download
)

from .progress_callback import ProgressStage, ProgressCallback, noop_callback


class PhoenixDownloader:
    """Async Phoenix Insurance document downloader using Playwright."""

    PORTAL_URL = "https://my.fnx.co.il"
    LOGIN_URL = "https://my.fnx.co.il"

    def __init__(
        self,
        user_id: str,
        phone: str,
        download_dir: Path,
        progress_callback: Optional[ProgressCallback] = None,
        headless: bool = True
    ):
        """
        Initialize the downloader.

        Args:
            user_id: Israeli ID number (9 digits)
            phone: Phone number (05XXXXXXXX)
            download_dir: Directory to save downloaded PDFs
            progress_callback: Async callback for progress updates
            headless: Whether to run browser in headless mode
        """
        self.user_id = user_id
        self.phone = phone
        self.download_dir = Path(download_dir)
        self.progress = progress_callback or noop_callback
        self.headless = headless

        self._playwright = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._cancelled = False
        self.download_count = 0

    async def __aenter__(self):
        """Enter async context - start browser."""
        self._playwright = await async_playwright().start()

        # Launch with args to avoid bot detection in headless mode
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-web-security',
                '--disable-features=IsolateOrigins,site-per-process',
            ] if self.headless else []
        )

        # Create context with realistic settings
        self._context = await self._browser.new_context(
            viewport={"width": 1400, "height": 900},
            locale="he-IL",
            accept_downloads=True,
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # Remove webdriver property to avoid detection
        await self._context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        self._page = await self._context.new_page()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Exit async context - close browser."""
        if self._context:
            await self._context.close()
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    def cancel(self):
        """Request cancellation of ongoing operation."""
        self._cancelled = True

    async def _check_cancelled(self):
        """Check if operation was cancelled and raise if so."""
        if self._cancelled:
            raise asyncio.CancelledError("Operation cancelled by user")

    async def _report_progress(
        self,
        stage: ProgressStage,
        message: str = None,
        current: int = None,
        total: int = None,
        error: Exception = None
    ):
        """Report progress through callback."""
        await self.progress(stage, message, current, total, error)

    def _clean_filename(self, name: str) -> str:
        """Clean a string for use as filename."""
        clean = re.sub(r'[<>:"/\\|?*]', '-', name)
        clean = re.sub(r'\s+', '_', clean)
        clean = clean[:60]
        return clean

    async def initiate_login(self) -> bool:
        """
        Phase 1: Enter credentials and request OTP.

        Navigates to login page, fills ID and phone, and requests OTP.
        The browser session remains open for the OTP entry phase.

        Returns:
            True if OTP was requested successfully, False otherwise.
        """
        await self._report_progress(ProgressStage.LOGIN_START)
        page = self._page

        try:
            # Navigate to login page
            await page.goto(self.LOGIN_URL, wait_until="networkidle", timeout=30000)
            await self._check_cancelled()

            # Wait for login form to load
            await page.wait_for_load_state("domcontentloaded")
            await asyncio.sleep(2)

            # Fill ID field
            id_input = page.get_by_role("textbox", name="מספר ת.ז*")
            await id_input.wait_for(state="visible", timeout=10000)
            await id_input.fill(self.user_id)

            await self._check_cancelled()

            # Fill phone field
            phone_input = page.get_by_role("textbox", name="טלפון נייד או כתובת מייל*")
            await phone_input.wait_for(state="visible", timeout=10000)
            await phone_input.fill(self.phone)

            await self._check_cancelled()

            # Click send OTP button
            send_btn = page.get_by_role("button", name="שלחו לי קוד כניסה")
            await send_btn.wait_for(state="visible", timeout=10000)
            await send_btn.click()

            # Wait for OTP input field to appear
            await asyncio.sleep(3)
            otp_field = page.locator("#otp")
            await otp_field.wait_for(state="visible", timeout=30000)

            await self._report_progress(ProgressStage.OTP_SENT)
            return True

        except PlaywrightTimeout as e:
            await self._report_progress(
                ProgressStage.ERROR,
                error=Exception(f"Timeout waiting for login form: {e}")
            )
            return False
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._report_progress(ProgressStage.ERROR, error=e)
            return False

    async def complete_login(self, otp: str) -> bool:
        """
        Phase 2: Enter OTP and complete login.

        Args:
            otp: The 6-digit OTP code received via SMS.

        Returns:
            True if login was successful, False otherwise.
        """
        page = self._page

        try:
            # Enter OTP
            otp_field = page.locator("#otp")
            await otp_field.fill(otp)

            await self._check_cancelled()

            # Click login button
            login_btn = page.get_by_role("button", name="כניסה")
            await login_btn.click()

            await asyncio.sleep(5)

            await self._check_cancelled()

            # Verify login success using multiple indicators (from original scraper)

            # Check for user name button (Hebrew name)
            try:
                user_button = page.get_by_role("button", name=re.compile(r"^[\u0590-\u05FF]+$"))
                await user_button.first.wait_for(timeout=10000)
                await self._report_progress(ProgressStage.LOGIN_COMPLETE)
                return True
            except PlaywrightTimeout:
                pass

            # Check for greeting text
            try:
                greeting = page.locator('h1:has-text("טובים")')
                if await greeting.count() > 0:
                    await self._report_progress(ProgressStage.LOGIN_COMPLETE)
                    return True
            except:
                pass

            # Check for policies section
            try:
                policies_section = page.locator('h2:has-text("הביטוחים שלך")')
                if await policies_section.count() > 0:
                    await self._report_progress(ProgressStage.LOGIN_COMPLETE)
                    return True
            except:
                pass

            # Check URL as last resort
            if "home" in page.url or "policies" in page.url:
                await self._report_progress(ProgressStage.LOGIN_COMPLETE)
                return True

            return False

        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._report_progress(ProgressStage.ERROR, error=e)
            return False

    async def download_health_documents(self) -> List[Path]:
        """
        Download all health insurance policy documents.

        Returns:
            List of paths to downloaded PDF files.
        """
        await self._report_progress(ProgressStage.FINDING_POLICIES)
        page = self._page
        downloaded_files: List[Path] = []

        self.download_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Navigate to home to see all policies
            await page.goto(f"{self.PORTAL_URL}/home", wait_until="networkidle", timeout=30000)
            await asyncio.sleep(3)

            # Scroll to load all content
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(2)

            await self._check_cancelled()

            # Find policy numbers from page content
            content = await page.content()
            policy_matches = re.findall(r'"(\d{10})"', content)

            # Filter unique policy numbers (exclude known non-policy numbers)
            exclude_numbers = {'1768837064', '2147482998', '2147483000', '2147483647'}
            policy_numbers = set()

            for num in policy_matches:
                if num not in exclude_numbers and not num.startswith("20") and not num.startswith("19"):
                    policy_numbers.add(num)

            if not policy_numbers:
                await self._report_progress(
                    ProgressStage.DOWNLOAD_COMPLETE,
                    message="לא נמצאו פוליסות בריאות",
                    current=0,
                    total=0
                )
                return downloaded_files

            await self._report_progress(
                ProgressStage.DOWNLOAD_START,
                message=f"נמצאו {len(policy_numbers)} פוליסות",
                current=0,
                total=len(policy_numbers)
            )

            # Process each policy
            policy_index = 0
            for policy_number in policy_numbers:
                await self._check_cancelled()
                policy_index += 1

                policy_dir = self.download_dir / f"policy_{policy_number}"
                policy_dir.mkdir(parents=True, exist_ok=True)
                appendices_dir = policy_dir / "appendices"
                appendices_dir.mkdir(exist_ok=True)

                try:
                    # Navigate to policy info page
                    url = f"{self.PORTAL_URL}/policies/health/{policy_number}/info"
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await asyncio.sleep(3)

                    # Scroll to load content
                    await page.evaluate("window.scrollTo(0, 500)")
                    await asyncio.sleep(1)

                    # Download appendices for main insured
                    main_downloads = await self._download_appendices_section(page, appendices_dir)
                    downloaded_files.extend(main_downloads)

                    # Handle additional insured persons
                    additional_buttons = page.get_by_role("button", name="לפרטים נוספים")
                    additional_count = await additional_buttons.count()

                    for i in range(additional_count):
                        await self._check_cancelled()
                        try:
                            # Re-find buttons (DOM changes)
                            additional_buttons = page.get_by_role("button", name="לפרטים נוספים")
                            btn = additional_buttons.nth(i)

                            # Get person name
                            parent = btn.locator('xpath=ancestor::div[contains(@class, "ng-star")]').first
                            name_elem = parent.locator('p').first
                            person_name = await name_elem.inner_text() if await name_elem.count() > 0 else f"מבוטח_{i+1}"

                            # Click to expand
                            await btn.click()
                            await asyncio.sleep(2)

                            # Create person directory
                            person_dir = appendices_dir / f"insured_{i+1}_{self._clean_filename(person_name)}"
                            person_dir.mkdir(exist_ok=True)

                            # Download their appendices
                            person_downloads = await self._download_appendices_section(page, person_dir)
                            downloaded_files.extend(person_downloads)

                            # Collapse section
                            await btn.click()
                            await asyncio.sleep(1)

                        except Exception as e:
                            continue

                    await self._report_progress(
                        ProgressStage.DOWNLOAD_PROGRESS,
                        message=f"פוליסה {policy_number}",
                        current=policy_index,
                        total=len(policy_numbers)
                    )

                except Exception as e:
                    continue

            await self._report_progress(
                ProgressStage.DOWNLOAD_COMPLETE,
                message=f"הורדתי {len(downloaded_files)} מסמכים",
                current=len(downloaded_files),
                total=len(downloaded_files)
            )

            return downloaded_files

        except asyncio.CancelledError:
            raise
        except Exception as e:
            await self._report_progress(ProgressStage.ERROR, error=e)
            raise

    async def _download_appendices_section(self, page: Page, save_dir: Path) -> List[Path]:
        """
        Download all appendices in current view.
        Based on the original phoenix-insurance-scraper logic.
        """
        downloaded: List[Path] = []

        # Find all appendix expand buttons
        expand_buttons = page.get_by_role("button", name="למידע נוסף לחץ")
        count = await expand_buttons.count()

        for i in range(count):
            await self._check_cancelled()

            try:
                # Re-find buttons each iteration (DOM changes)
                expand_buttons = page.get_by_role("button", name="למידע נוסף לחץ")
                btn = expand_buttons.nth(i)

                # Check if already expanded
                is_expanded = await btn.get_attribute("aria-expanded")

                # Get appendix name from heading
                parent_container = btn.locator('xpath=ancestor::div[1]')
                heading = parent_container.locator('h5').first
                appendix_name = await heading.inner_text() if await heading.count() > 0 else f"נספח_{i+1}"

                # Expand if needed
                if is_expanded != "true":
                    await btn.click()
                    await asyncio.sleep(2)

                # Find the download button for "הנספח המלא"
                full_appendix_text = page.locator('p:has-text("הנספח המלא")')

                if await full_appendix_text.count() > 0:
                    # Get the parent div and find the button inside it
                    download_container = full_appendix_text.first.locator('xpath=parent::div')
                    download_btn = download_container.locator('button').first

                    if await download_btn.count() > 0:
                        try:
                            async with page.expect_download(timeout=30000) as download_info:
                                await download_btn.click()

                            download: Download = await download_info.value
                            filename = download.suggested_filename or "appendix.pdf"

                            # Create unique filename
                            clean_name = self._clean_filename(appendix_name)
                            save_path = save_dir / f"{i+1:02d}_{clean_name}_{filename}"

                            await download.save_as(save_path)
                            self.download_count += 1
                            downloaded.append(save_path)

                        except PlaywrightTimeout:
                            pass
                        except Exception as e:
                            pass

                # Collapse the expanded section
                try:
                    expand_buttons = page.get_by_role("button", name="למידע נוסף לחץ")
                    btn = expand_buttons.nth(i)
                    is_exp = await btn.get_attribute("aria-expanded")
                    if is_exp == "true":
                        await btn.click()
                        await asyncio.sleep(0.5)
                except:
                    pass

            except Exception as e:
                continue

        return downloaded

    async def get_policies_count(self) -> int:
        """Get the number of health policies found."""
        page = self._page
        try:
            content = await page.content()
            policy_matches = re.findall(r'"(\d{10})"', content)
            exclude_numbers = {'1768837064', '2147482998', '2147483000', '2147483647'}
            policy_numbers = set()
            for num in policy_matches:
                if num not in exclude_numbers and not num.startswith("20") and not num.startswith("19"):
                    policy_numbers.add(num)
            return len(policy_numbers)
        except Exception:
            return 0
