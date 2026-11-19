"""The Playwright layer: find things, click them, type into them. Decide nothing.

Every selector here comes from the portal's own ``data-testid`` attributes, which are
stable across builds. No positional selectors, no CSS-path guessing, no text matching
where a testid exists.

Two portal behaviours shape the code:

**Virtual scrolling.** The SKU table renders only the rows in view - a saved page with
17 rows contained 9. Rows are therefore never collected into a list and iterated; each
row is addressed by its ``data-row-key`` and filled where it stands.

**Shadow DOM.** The portal is built from web components with ``shadowrootmode="open"``.
Playwright's CSS engine pierces open shadow roots, so ``[data-testid="..."]`` matches
inside them. Where a click must land on the real ``<button>`` inside a component, the
selector descends into the shadow root explicitly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

#: Where the operator logs in once. The session lives in our own profile folder.
HOME_URL = "https://www.maersk.com/scp"

#: Time to wait for a page-level condition.
DEFAULT_TIMEOUT = 30_000

#: Where Maersk sends you to sign in. The real one is ``accounts.maersk.com`` -
#: note the plural; ``account.maersk.com`` would never match it.
LOGIN_HOSTS = (
    "accounts.maersk.com",
    "login.microsoftonline.com",
    "forgerock",
    "pingfed",
    "pingone",
    "okta.com",
    "auth0.com",
)

#: Paths that mean "sign-in is in flight" - the OIDC callback bounces through here on
#: the way back to the portal, so treating it as signed-in would navigate too early.
LOGIN_PATHS = (
    "/ocean-maeu/auth/login",
    "/portaluser/oidc/callback",
    "/login",
    "/authorize",
)

#: A URL on this host, with none of the above, is the portal itself.
PORTAL_HOST = "maersk.com"
PORTAL_PATH = "/scp"

#: How long to give the operator to sign in by hand. Generous on purpose: a password
#: manager, a second factor and a slow corporate VPN can easily take a few minutes.
LOGIN_TIMEOUT_S = 600


class PortalError(RuntimeError):
    """Something on the page did not look the way the mapping says it should."""


@dataclass
class Selectors:
    """Every selector used, in one place, so a portal change is a one-line edit."""

    # -- left navigation -------------------------------------------------
    nav_export: str = 'nav >> text="Export"'
    nav_bookings: str = 'text="Bookings"'

    # -- bookings list ---------------------------------------------------
    filters_button: str = 'button:has-text("Filters")'
    order_field: str = (
        'input[data-testid="order"], '
        'input[placeholder="Order"], '
        '.filters-panel input[name="order"]'
    )
    apply_filters: str = 'button:has-text("Apply filters")'
    clear_filters: str = 'button:has-text("Clear filters")'
    no_bookings_found: str = 'text="No bookings found"'

    # -- edit page -------------------------------------------------------
    edit_booking: str = 'button:has-text("Edit booking")'
    save_draft: str = '[data-testid="booking-header-save-draft"]'
    review_button: str = '[data-testid="booking-header-next"]'
    submit_button: str = '[data-testid="booking-header-submit"]'
    review_errors: str = '[data-testid="booking-create-review-errors-count"]'
    invoice_currency: str = '[data-testid="commercial-invoice-currency"]'

    # -- reviewed totals -------------------------------------------------
    review_totals: str = "booking-create-review-orders"


def totals_selectors(label_prefix: str) -> str:
    """The label/value pair for one reviewed total, matched by prefix.

    The portal appends its unit to the label, and the wording differs between the edit
    page and the Review page (``Total gross weight (kg)`` vs ``Total weight (kg)
    (KILOGRAM)``), so a prefix match is the only version that survives both.
    """
    return (f'span.review-data-label:has-text("{label_prefix}")'
            f' + span.review-data-value')


class Driver:
    """A thin, boring wrapper over a Playwright page."""

    #: Kept on the class so a caller can read the default without importing the module.
    LOGIN_TIMEOUT_S = LOGIN_TIMEOUT_S

    def __init__(self, page, selectors: Selectors | None = None) -> None:
        self.page = page
        self.sel = selectors or Selectors()

    # -- sign-in ---------------------------------------------------------
    def signed_in(self) -> bool:
        """True when the page is the portal rather than a sign-in screen.

        Detection is about *where we are*, not about cookies:

        * a sign-in host, or a sign-in/callback path -> not signed in yet;
        * the portal host with the portal path -> signed in;
        * anything else (about:blank, a redirect in flight) -> not signed in yet, so the
          caller keeps waiting rather than acting on a half-loaded page.
        """
        url = (self.page.url or "").lower()
        if not url or url.startswith("about:"):
            return False
        if any(host in url for host in LOGIN_HOSTS):
            return False
        if any(path in url for path in LOGIN_PATHS):
            return False
        return PORTAL_HOST in url and PORTAL_PATH in url

    def wait_for_sign_in(self, timeout_s: int = LOGIN_TIMEOUT_S,
                         on_wait=None) -> bool:
        """Block until the operator has signed in, or ``timeout_s`` elapses.

        Autobook never asks for, sees or stores a password: the operator types into
        Maersk's own sign-in page. This simply waits for that to finish.
        """
        import time

        deadline = time.monotonic() + timeout_s
        announced = False
        while time.monotonic() < deadline:
            if self.signed_in():
                return True
            if not announced and on_wait:
                on_wait("Sign in to Maersk in the browser window. Autobook is waiting...")
                announced = True
            self.page.wait_for_timeout(1000)
        return False

    def open_portal(self) -> None:
        """Go to the portal home, which redirects to sign-in when the session has lapsed."""
        self.page.goto(HOME_URL, wait_until="domcontentloaded")

    # -- waiting ---------------------------------------------------------
    def wait_for(self, selector: str, timeout: int = DEFAULT_TIMEOUT):
        return self.page.wait_for_selector(selector, timeout=timeout, state="visible")

    def wait_for_any(self, selectors: list[str], timeout: int = DEFAULT_TIMEOUT) -> str:
        """Wait until one of ``selectors`` is visible; return it.

        Used where the portal can legitimately show either a result or an empty state.
        """
        import time

        deadline = time.monotonic() + timeout / 1000
        while time.monotonic() < deadline:
            for selector in selectors:
                if self.page.locator(selector).count():
                    if self.page.locator(selector).first.is_visible():
                        return selector
            self.page.wait_for_timeout(250)
        raise PortalError("None of these appeared: " + ", ".join(selectors))

    # -- diagnosis -------------------------------------------------------
    def snapshot(self, folder, label: str = "failure") -> dict[str, str]:
        """Save a screenshot and the page HTML, plus the current URL.

        A failing selector is nearly impossible to fix from a traceback alone; this
        produces the two things that make it a one-line fix - what the page looked like
        and what the DOM actually contained.
        """
        import re
        from pathlib import Path

        out = Path(folder)
        out.mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", label)[:60]
        made: dict[str, str] = {}
        try:
            made["url"] = self.page.url
            image = out / f"{safe}.png"
            self.page.screenshot(path=str(image), full_page=False)
            made["screenshot"] = str(image)
            html = out / f"{safe}.html"
            html.write_text(self.page.content(), encoding="utf-8")
            made["html"] = str(html)
        except Exception:                # diagnosis must never mask the real failure
            logger.warning("could not capture the page", exc_info=True)
        return made

    # -- left navigation -------------------------------------------------
    def open_bookings(self) -> None:
        """Export (flyout) ▸ Bookings. The flyout needs a hover, then a click."""
        export = self.page.locator(self.sel.nav_export).first
        export.hover()
        bookings = self.page.locator(self.sel.nav_bookings).first
        bookings.wait_for(state="visible")
        bookings.click()
        logger.info("opened Bookings")

    # -- filters ---------------------------------------------------------
    def filter_by_order(self, po_no: str) -> None:
        """Type the PO into ``Order`` and apply. The field is found by its label."""
        self.page.locator(self.sel.filters_button).first.click()
        field = self.page.locator(self.sel.order_field).first
        field.wait_for(state="visible")
        field.fill(po_no)
        self.page.locator(self.sel.apply_filters).first.click()
        logger.info("filtered by order %s", po_no)

    def clear_filters(self) -> None:
        self.page.locator(self.sel.clear_filters).first.click()
        logger.info("filters cleared")

    def result_state(self) -> str:
        """``"empty"`` or ``"rows"`` - which the portal is showing after a filter."""
        empty = self.page.locator(self.sel.no_bookings_found)
        if empty.count() and empty.first.is_visible():
            return "empty"
        return "rows"

    def booking_rows(self) -> list[dict[str, str]]:
        """The matched rows: booking number and status.

        Read from the row's own cells so the user can be offered the choices, and so a
        skip status can be recognised before anything is clicked.
        """
        rows = []
        for row in self.page.locator("tbody tr").all():
            cells = row.locator("td").all_inner_texts()
            if len(cells) >= 2:
                rows.append({
                    "booking": cells[0].strip(),
                    "status": cells[-1].strip() if cells[-1].strip() else "",
                    "text": " | ".join(c.strip() for c in cells),
                })
        return rows

    def open_booking(self, booking_no: str) -> None:
        self.page.locator(f'a:has-text("{booking_no}"), text="{booking_no}"').first.click()
        logger.info("opened booking %s", booking_no)

    # -- edit page -------------------------------------------------------
    def back_to_bookings(self) -> None:
        """Return from a booking page to the list.

        Needed between POs: the next PO starts by filtering, and that is meaningless
        while an edit page is still open.
        """
        back = self.page.get_by_text("Bookings", exact=True)
        if back.count():
            back.first.click()
            self.page.locator(self.sel.filters_button).first.wait_for(state="visible")
        logger.info("back to the bookings list")

    def start_editing(self) -> None:
        """Click ``Edit booking``.

        ``Cancel booking`` sits immediately beside it, so the locator is anchored on the
        exact text and the click target is verified before use.
        """
        button = self.page.get_by_role("button", name="Edit booking")
        button.wait_for(state="visible")
        button.click()
        logger.info("clicked Edit booking")

    def set_invoice_currency(self, currency: str = "USD") -> None:
        field = self.page.locator(self.sel.invoice_currency).first
        field.wait_for(state="visible")
        field.fill(currency)

    def ensure_po_expanded(self, po_no: str) -> None:
        """Expand the PO card **only if** it is collapsed.

        Clicking an already-open card would collapse it and hide the grid.
        """
        expanded = self.page.locator('[data-testid="po-sku-edit-expanded"]')
        if expanded.count() and expanded.first.is_visible():
            return
        toggle = self.page.locator(f'[data-testid="po-sku-edit-toggle-expand"]').first
        toggle.wait_for(state="visible")
        toggle.click()
        expanded.first.wait_for(state="visible")

    # -- grid ------------------------------------------------------------
    def row_keys(self) -> list[str]:
        """Row keys currently rendered. **Not** the full list under virtual scrolling."""
        return [row.get_attribute("data-row-key")
                for row in self.page.locator("tr[data-row-key]").all()]

    def sku_text(self, key: str) -> str:
        row = self.page.locator(f'tr[data-row-key="{key}"]')
        cell = row.locator(".po-sku-edit-sku-cell-text").first
        return cell.inner_text().strip() if cell.count() else ""

    def fill_row_field(self, key: str, field: str, value: object) -> None:
        """Type into one input of one row."""
        selector = f'[data-testid="po-sku-edit-table-{field}-{key}"]'
        target = self.page.locator(selector).first
        target.wait_for(state="visible")
        target.fill(str(value))

    def read_row_field(self, key: str, field: str) -> str:
        selector = f'[data-testid="po-sku-edit-table-{field}-{key}"]'
        target = self.page.locator(selector).first
        return target.input_value() if target.count() else ""

    def select_row_option(self, key: str, field: str, label: str) -> None:
        """Choose from a portal dropdown by its visible label (``Flat pack``)."""
        wrapper = self.page.locator(
            f'mc-select-native-v2[data-testid="po-sku-edit-table-{field}-{key}"]')
        wrapper.locator("select").select_option(label=label)

    def scroll_rows_once(self) -> bool:
        """Scroll the grid by one page. False when it is already at the end.

        Virtual scrolling means a row only exists once it has been rendered, so finding a
        row that is off screen means scrolling to it.
        """
        return bool(self.page.evaluate(
            """() => {
                const bar = document.querySelector('[data-testid="po-sku-edit-table-vscroll-bar"]');
                const scroller = document.querySelector('.po-sku-edit-table-wrap');
                const el = bar ? (bar.closest('[class*=scroll]') || scroller) : scroller;
                if (!el) return false;
                const before = el.scrollTop;
                el.scrollTop = before + el.clientHeight * 0.8;
                return el.scrollTop > before;
            }"""
        ))

    def commodity_code_of(self, key: str) -> str:
        selector = (f'[data-testid$="commodity-inline-{key}-commodity-code-0"]')
        target = self.page.locator(selector).first
        return target.input_value() if target.count() else ""

    def fill_commodity_code(self, key: str, code: str) -> None:
        selector = (f'[data-testid$="commodity-inline-{key}-commodity-code-0"]')
        self.page.locator(selector).first.fill(code)

    # -- review ----------------------------------------------------------
    def save_draft(self) -> None:
        self.page.locator(self.sel.save_draft).first.click()
        logger.info("saved draft")

    def go_to_review(self) -> None:
        self.page.locator(self.sel.review_button).first.click()
        self.page.locator(f'[data-testid="{self.sel.review_totals}"]').first.wait_for(
            state="visible")
        logger.info("on the review page")

    def review_total(self, label_prefix: str) -> str:
        target = self.page.locator(totals_selectors(label_prefix)).first
        return target.inner_text().strip() if target.count() else ""

    def review_errors(self) -> str:
        target = self.page.locator(self.sel.review_errors).first
        return target.inner_text().strip() if target.count() else ""

    def submit(self) -> None:
        self.page.locator(self.sel.submit_button).first.click()
        logger.info("submitted")


#: The port Edge is asked to listen on when the operator wants to attach to a browser
#: they started themselves.
DEBUG_PORT = 9222


def launch(profile_dir: Path, headless: bool = False, channel: str = "msedge",
           attach: bool = False, port: int = DEBUG_PORT):
    """Return ``(playwright, context)`` for the browser the operator is logged into.

    Two modes, because they solve different problems:

    ``attach=False`` (default)
        Launch our own browser with a **dedicated profile folder**. The operator logs in
        once inside it and the session persists. This is the reliable mode: we control
        the browser, so we can close and restart it cleanly.

    ``attach=True``
        Connect to a browser **the operator started**, already logged in. Nothing new
        opens and the existing session is used as-is. The trade-off is that the browser
        must be started with remote debugging enabled and a **non-default** profile:
        current Chrome and Edge refuse debugging on the default profile, so a separate
        ``--user-data-dir`` is unavoidable either way.
    """
    from playwright.sync_api import sync_playwright

    playwright = sync_playwright().start()

    if attach:
        browser = playwright.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
        # Reuse the operator's existing tab rather than opening a new one, so the run
        # happens in the window they are watching.
        context = browser.contexts[0] if browser.contexts else browser.new_context()
        return playwright, context

    profile_dir = Path(profile_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    context = playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        channel=channel,
        headless=headless,
        viewport={"width": 1600, "height": 1000},
    )
    return playwright, context
