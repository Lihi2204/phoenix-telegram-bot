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
        import logging
        logger = logging.getLogger(__name__)

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

            # Log available policy types/sections on the page
            content = await page.content()

            # Check for policy type indicators
            policy_types = []
            if 'health' in content.lower() or 'בריאות' in content:
                policy_types.append('health/בריאות')
            if 'life' in content.lower() or 'חיים' in content:
                policy_types.append('life/חיים')
            if 'pension' in content.lower() or 'פנסיה' in content:
                policy_types.append('pension/פנסיה')
            if 'car' in content.lower() or 'רכב' in content:
                policy_types.append('car/רכב')

            logger.info(f"Detected policy types on page: {policy_types}")

            # Find policy numbers from page content
            policy_matches = re.findall(r'"(\d{10})"', content)

            logger.info(f"Found {len(policy_matches)} potential policy numbers in page content")

            # Filter unique policy numbers (exclude known non-policy numbers)
            exclude_numbers = {'1768837064', '2147482998', '2147483000', '2147483647'}
            policy_numbers = set()

            for num in policy_matches:
                if num not in exclude_numbers and not num.startswith("20") and not num.startswith("19"):
                    policy_numbers.add(num)

            logger.info(f"After filtering: {len(policy_numbers)} unique health policy numbers: {policy_numbers}")

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

                logger.info(f"Processing policy {policy_index}/{len(policy_numbers)}: {policy_number}")

                policy_dir = self.download_dir / f"policy_{policy_number}"
                policy_dir.mkdir(parents=True, exist_ok=True)
                appendices_dir = policy_dir / "appendices"
                appendices_dir.mkdir(exist_ok=True)

                try:
                    # Navigate to policy info page
                    url = f"{self.PORTAL_URL}/policies/health/{policy_number}/info"
                    logger.info(f"Navigating to: {url}")
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    await asyncio.sleep(3)

                    # Scroll to load content
                    await page.evaluate("window.scrollTo(0, 500)")
                    await asyncio.sleep(1)

                    # Download policy details PDF (contains personal exclusions)
                    policy_details_path = await self._download_policy_details(page, policy_dir, policy_number)
                    if policy_details_path:
                        downloaded_files.append(policy_details_path)
                        self.download_count += 1

                    # Download appendices for main insured
                    main_downloads = await self._download_appendices_section(page, appendices_dir)
                    downloaded_files.extend(main_downloads)

                    # Handle additional insured persons
                    additional_buttons = page.get_by_role("button", name="לפרטים נוספים")
                    additional_count = await additional_buttons.count()
                    logger.info(f"Found {additional_count} additional insured persons in policy {policy_number}")

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
                            logger.info(f"Downloaded {len(person_downloads)} appendices for {person_name}")

                            # Collapse section
                            await btn.click()
                            await asyncio.sleep(1)

                        except Exception as e:
                            logger.error(f"Error processing additional insured {i+1}: {e}")
                            continue

                    policy_file_count = len(main_downloads) + sum(len(p) for p in [person_downloads] if 'person_downloads' in dir())
                    logger.info(f"Policy {policy_number} complete: downloaded {len(main_downloads)} main appendices + additional insured appendices")

                    await self._report_progress(
                        ProgressStage.DOWNLOAD_PROGRESS,
                        message=f"פוליסה {policy_number}",
                        current=policy_index,
                        total=len(policy_numbers)
                    )

                except Exception as e:
                    logger.error(f"Error processing policy {policy_number}: {e}")
                    continue

            # Final summary
            logger.info("=" * 50)
            logger.info("DOWNLOAD SUMMARY")
            logger.info(f"Total policies processed: {len(policy_numbers)}")
            logger.info(f"Total files downloaded: {len(downloaded_files)}")
            logger.info("=" * 50)

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

    async def _download_policy_details(self, page: Page, save_dir: Path, policy_number: str) -> Optional[Path]:
        """
        Download the policy details PDF (העתק תעודת ביטוח).

        This document contains critical information including personal exclusions
        (החרגות אישיות) that are not in the appendices.

        Args:
            page: Playwright page object
            save_dir: Directory to save the PDF
            policy_number: Policy number for filename

        Returns:
            Path to downloaded PDF or None if failed
        """
        import logging
        logger = logging.getLogger(__name__)

        # Selectors for the policy details link in left menu
        policy_details_selectors = [
            'a:has-text("העתק תעודת ביטוח")',
            'button:has-text("העתק תעודת ביטוח")',
            '[data-test*="certificate"]',
            'a:has-text("תעודת ביטוח")',
            'button:has-text("תעודת ביטוח")',
        ]

        try:
            logger.info(f"Looking for policy details button for policy {policy_number}")

            details_link = None
            for selector in policy_details_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0:
                        details_link = element
                        logger.info(f"Found policy details link with selector: {selector}")
                        break
                except Exception:
                    continue

            if not details_link:
                logger.warning(f"Could not find policy details link for policy {policy_number}")
                return None

            # Click the link - this may open a new tab/window or trigger a download
            # The PDF generation can take 2-3 minutes according to user
            logger.info("Clicking policy details link, waiting for PDF (may take up to 3 minutes)...")

            # Set up listeners for both new page (popup) and download
            async with self._context.expect_page(timeout=180000) as new_page_info:
                try:
                    await details_link.click()
                except Exception as click_error:
                    logger.warning(f"Click error: {click_error}, trying JavaScript click")
                    await details_link.evaluate("el => el.click()")

            # Wait for new page/popup with PDF
            try:
                new_page = await new_page_info.value
                logger.info(f"New page opened: {new_page.url}")

                # Wait for page to load
                await new_page.wait_for_load_state("networkidle", timeout=180000)
                await asyncio.sleep(2)

                # Check if it's a PDF viewer or direct PDF
                current_url = new_page.url

                if current_url.endswith('.pdf') or 'pdf' in current_url.lower():
                    # Direct PDF URL - download it
                    save_path = save_dir / f"policy_details_{policy_number}.pdf"

                    # Try to download using the browser's download mechanism
                    async with new_page.expect_download(timeout=60000) as download_info:
                        # Trigger download by pressing Ctrl+S or clicking download button
                        await new_page.keyboard.press("Control+s")

                    download = await download_info.value
                    await download.save_as(save_path)
                    logger.info(f"Downloaded policy details to {save_path}")
                    await new_page.close()
                    return save_path

                else:
                    # It might be a PDF viewer - look for download button or print
                    # Try to find and click a download/print button
                    download_btns = [
                        'button:has-text("הורדה")',
                        'button:has-text("שמירה")',
                        'a:has-text("הורדה")',
                        '[aria-label*="download"]',
                        '[aria-label*="הורדה"]',
                    ]

                    for btn_selector in download_btns:
                        try:
                            btn = new_page.locator(btn_selector).first
                            if await btn.count() > 0:
                                async with new_page.expect_download(timeout=60000) as download_info:
                                    await btn.click()
                                download = await download_info.value
                                save_path = save_dir / f"policy_details_{policy_number}.pdf"
                                await download.save_as(save_path)
                                logger.info(f"Downloaded policy details to {save_path}")
                                await new_page.close()
                                return save_path
                        except Exception:
                            continue

                    # If no download button found, try printing to PDF
                    logger.info("Trying to capture PDF from page content...")
                    save_path = save_dir / f"policy_details_{policy_number}.pdf"
                    await new_page.pdf(path=str(save_path))
                    logger.info(f"Saved policy details PDF to {save_path}")
                    await new_page.close()
                    return save_path

            except PlaywrightTimeout:
                logger.warning("Timeout waiting for new page with policy details PDF")

        except PlaywrightTimeout:
            logger.warning(f"Timeout waiting for policy details PDF for policy {policy_number}")
        except Exception as e:
            logger.error(f"Error downloading policy details for {policy_number}: {e}")

        # Alternative: Try expect_download directly without new page
        try:
            logger.info("Trying alternative download method...")
            details_link = None
            for selector in policy_details_selectors:
                try:
                    element = page.locator(selector).first
                    if await element.count() > 0:
                        details_link = element
                        break
                except Exception:
                    continue

            if details_link:
                async with page.expect_download(timeout=180000) as download_info:
                    await details_link.click()

                download = await download_info.value
                save_path = save_dir / f"policy_details_{policy_number}.pdf"
                await download.save_as(save_path)
                logger.info(f"Downloaded policy details (alternative method) to {save_path}")
                return save_path

        except Exception as e:
            logger.error(f"Alternative download method also failed: {e}")

        return None

    async def _download_appendices_section(self, page: Page, save_dir: Path) -> List[Path]:
        """
        Download all appendices in current view.
        Based on the original phoenix-insurance-scraper logic.
        """
        import logging
        logger = logging.getLogger(__name__)

        downloaded: List[Path] = []

        # Find all appendix expand buttons
        expand_buttons = page.get_by_role("button", name="למידע נוסף לחץ")
        count = await expand_buttons.count()
        logger.info(f"Found {count} appendix expand buttons in {save_dir}")

        for i in range(count):
            await self._check_cancelled()

            try:
                # Re-find buttons each iteration (DOM changes)
                expand_buttons = page.get_by_role("button", name="למידע נוסף לחץ")
                btn = expand_buttons.nth(i)

                # Check if already expanded
                is_expanded = await btn.get_attribute("aria-expanded")

                # Get appendix name from heading - look in parent container
                parent_container = btn.locator('xpath=ancestor::div[contains(@class, "accordion") or contains(@class, "expansion")]').first
                if await parent_container.count() == 0:
                    parent_container = btn.locator('xpath=ancestor::div[1]')
                heading = parent_container.locator('h5').first
                appendix_name = await heading.inner_text() if await heading.count() > 0 else f"נספח_{i+1}"
                logger.info(f"Processing appendix {i+1}/{count}: {appendix_name}")

                # Expand if needed
                if is_expanded != "true":
                    await btn.click()
                    await asyncio.sleep(2)

                # Find the download button for "הנספח המלא" within the expanded section
                # Look for it relative to the expanded button's container
                expanded_section = btn.locator('xpath=following-sibling::div[1]')
                full_appendix_text = expanded_section.locator('p:has-text("הנספח המלא")')

                # If not found in sibling, try the parent's scope
                if await full_appendix_text.count() == 0:
                    full_appendix_text = parent_container.locator('p:has-text("הנספח המלא")')

                # Last resort: search in page but be more specific
                if await full_appendix_text.count() == 0:
                    full_appendix_text = page.locator('p:has-text("הנספח המלא")').first

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
                            logger.info(f"Downloaded appendix {i+1}: {save_path.name}")

                        except PlaywrightTimeout:
                            logger.warning(f"Timeout downloading appendix {i+1}: {appendix_name}")
                        except Exception as e:
                            logger.error(f"Error downloading appendix {i+1}: {e}")
                    else:
                        logger.warning(f"No download button found for appendix {i+1}: {appendix_name}")
                else:
                    logger.warning(f"No 'הנספח המלא' text found for appendix {i+1}: {appendix_name}")

                # Collapse the expanded section
                try:
                    expand_buttons = page.get_by_role("button", name="למידע נוסף לחץ")
                    btn = expand_buttons.nth(i)
                    is_exp = await btn.get_attribute("aria-expanded")
                    if is_exp == "true":
                        await btn.click()
                        await asyncio.sleep(0.5)
                except Exception as collapse_err:
                    logger.debug(f"Could not collapse appendix {i+1}: {collapse_err}")

            except Exception as e:
                logger.error(f"Error processing appendix {i+1}: {e}")
                continue

        logger.info(f"Downloaded {len(downloaded)} appendices from {save_dir}")
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
