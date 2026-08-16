"""A long-lived browser the app owns, so the buyer signs in once and never again.

Playwright's sync objects belong to the thread that made them, and the web app
serves each request on a new thread. So all browser work is funnelled to one
worker thread through a queue: callers submit a function, the worker runs it
against the live page and hands the result back.

The browser is launched with a persistent profile directory, which is what makes
the Weee! session survive between runs. Sign in once, and every later click goes
straight to the cart.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from mandatelab_weee_cart.selectors import CART_URL, DEFAULT, Selectors

# A stable location, deliberately not /tmp: the whole point is that the login
# outlives a reboot.
DEFAULT_PROFILE_DIR = Path.home() / ".mandatelab" / "weee-profile"
WEEE_HOME = "https://www.sayweee.com/en"
LOGIN_URL = "https://www.sayweee.com/en/account/login"


@dataclass
class BrowserStatus:
    running: bool
    signed_in: bool | None  # None when it cannot be determined
    detail: str
    profile_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "running": self.running,
            "signed_in": self.signed_in,
            "detail": self.detail,
            "profile_dir": self.profile_dir,
        }


class _Job:
    __slots__ = ("fn", "done", "result", "error")

    def __init__(self, fn: Callable[[Any], Any]) -> None:
        self.fn = fn
        self.done = threading.Event()
        self.result: Any = None
        self.error: BaseException | None = None


class BrowserWorker:
    """Owns one Playwright browser on a dedicated thread."""

    def __init__(
        self,
        profile_dir: Path = DEFAULT_PROFILE_DIR,
        selectors: Selectors = DEFAULT,
        headless: bool = False,
        cdp_url: str | None = None,
    ) -> None:
        self.profile_dir = Path(profile_dir)
        self.selectors = selectors
        self.headless = headless
        self.cdp_url = cdp_url
        self._jobs: queue.Queue[_Job | None] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._start_error: str | None = None

    # -- lifecycle ---------------------------------------------------------

    def ensure_started(self) -> str | None:
        """Start the browser if it is not already up. Returns an error, or None."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return None
            self._start_error = None
            ready = threading.Event()
            self._thread = threading.Thread(
                target=self._run, args=(ready,), name="weee-browser", daemon=True
            )
            self._thread.start()
            ready.wait(timeout=90)
            return self._start_error

    def _run(self, ready: threading.Event) -> None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            self._start_error = f"playwright is not installed: {exc}"
            ready.set()
            return

        playwright = None
        context = None
        try:
            playwright = sync_playwright().start()
            if self.cdp_url:
                browser = playwright.chromium.connect_over_cdp(self.cdp_url)
                context = browser.contexts[0] if browser.contexts else browser.new_context()
            else:
                self.profile_dir.mkdir(parents=True, exist_ok=True)
                # A browser killed mid-shutdown can leave the profile locked for
                # a moment. Retry rather than failing the click.
                context = None
                for attempt in range(3):
                    try:
                        kwargs = dict(
                            headless=self.headless,
                            viewport={"width": 1280, "height": 900},
                            args=["--disable-blink-features=AutomationControlled"],
                        )
                        # Prefer the real Google Chrome the buyer already has;
                        # fall back to Playwright's Chromium if it is absent.
                        try:
                            context = playwright.chromium.launch_persistent_context(
                                str(self.profile_dir), channel="chrome", **kwargs
                            )
                        except Exception:
                            context = playwright.chromium.launch_persistent_context(
                                str(self.profile_dir), **kwargs
                            )
                        break
                    except Exception:
                        if attempt == 2:
                            raise
                        for lock in ("SingletonLock", "SingletonCookie", "SingletonSocket"):
                            (self.profile_dir / lock).unlink(missing_ok=True)
                        time.sleep(2)
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(20000)
        except Exception as exc:
            self._start_error = f"could not start a browser: {exc}"
            ready.set()
            if playwright:
                try:
                    playwright.stop()
                except Exception:
                    pass
            return

        ready.set()
        try:
            while True:
                job = self._jobs.get()
                if job is None:
                    break
                try:
                    job.result = job.fn(page)
                except Exception as exc:  # surface, never crash the worker
                    job.error = exc
                finally:
                    job.done.set()
        finally:
            for closer in (context, playwright):
                try:
                    closer.close() if closer is context else closer.stop()
                except Exception:
                    pass

    def submit(self, fn: Callable[[Any], Any], timeout: float = 180.0, _retry: bool = True) -> Any:
        """Run `fn(page)` on the browser thread and return its result.

        If the window was closed underneath us, rebuild the browser once and try
        again -- one closed tab should not fail every remaining item.
        """
        error = self.ensure_started()
        if error:
            raise RuntimeError(error)
        job = _Job(fn)
        self._jobs.put(job)
        if not job.done.wait(timeout=timeout):
            raise TimeoutError("browser job timed out")
        if job.error:
            closed = "has been closed" in str(job.error) or "Target page" in str(job.error)
            if closed and _retry:
                self.stop()
                self._thread = None
                return self.submit(fn, timeout=timeout, _retry=False)
            raise job.error
        return job.result

    def stop(self) -> None:
        if self._thread and self._thread.is_alive():
            self._jobs.put(None)
            self._thread.join(timeout=10)

    @property
    def running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    # -- operations --------------------------------------------------------

    def status(self) -> BrowserStatus:
        if not self.running:
            return BrowserStatus(
                running=False,
                signed_in=None,
                detail="browser not started yet",
                profile_dir=str(self.profile_dir),
            )
        try:
            signed_in, detail = self.submit(self._check_signed_in, timeout=60)
        except Exception as exc:
            return BrowserStatus(True, None, f"could not check session: {exc}", str(self.profile_dir))
        return BrowserStatus(True, signed_in, detail, str(self.profile_dir))

    def _check_signed_in(self, page) -> tuple[bool | None, str]:
        """Best-effort session check.

        Returns None rather than guessing when the page gives no clear answer --
        a wrong "signed in" would send the executor off to click nothing.
        """
        page.goto(CART_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(1200)
        url = page.url.lower()
        if "login" in url or "signin" in url:
            return False, "Weee! redirected to the sign-in page"
        for selector in self.selectors.login_marker:
            try:
                if page.locator(selector).count() > 0:
                    return False, "sign-in prompt visible on the cart page"
            except Exception:
                continue
        return True, "cart page reachable without a sign-in prompt"

    def open_login(self) -> str:
        """Bring the browser to the Weee! sign-in page for the buyer to use."""
        def go(page):
            page.goto(LOGIN_URL, wait_until="domcontentloaded")
            try:
                page.bring_to_front()
            except Exception:
                pass
            return page.url

        return self.submit(go, timeout=90)
