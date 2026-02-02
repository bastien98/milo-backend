import time
import re
import random
import pandas as pd
from datetime import datetime
from playwright.sync_api import sync_playwright

# Configuration
CARREFOUR_URL = "https://www.carrefour.be/nl/al-onze-promoties"
BASE_URL = "https://www.carrefour.be"
OUTPUT_FILE = "carrefour_promotions.csv"


def random_delay(min_sec=1, max_sec=3):
    """Human-like random delay."""
    time.sleep(random.uniform(min_sec, max_sec))


def parse_date(date_text):
    """Extract date from text like 'Aanbieding geldig t.e.m. 09/02/2026'"""
    try:
        match = re.search(r'(\d{2}/\d{2}/\d{4})', date_text)
        if match:
            dt = datetime.strptime(match.group(1), "%d/%m/%Y")
            return dt.strftime("%Y-%m-%d")
    except Exception:
        pass
    return None


def handle_cookie_consent(page):
    """Handle cookie consent popups."""
    print("🍪 Checking for cookie consent popup...")
    random_delay(1, 2)

    cookie_selectors = [
        "#onetrust-accept-btn-handler",
        "button:has-text('Accepteren')",
        "button:has-text('Alles accepteren')",
        "button:has-text('Accept all')",
    ]

    for selector in cookie_selectors:
        try:
            button = page.query_selector(selector)
            if button and button.is_visible():
                print(f"   Found cookie button")
                random_delay(0.5, 1)
                button.click()
                random_delay(1, 2)
                print("   ✅ Cookie consent accepted")
                return True
        except Exception:
            continue

    print("   No cookie popup found")
    return False


def human_scroll(page):
    """Scroll like a human - smooth and with pauses."""
    # Scroll down in smaller increments
    scroll_amount = random.randint(300, 600)
    page.evaluate(f"window.scrollBy(0, {scroll_amount})")
    random_delay(0.3, 0.8)


def click_load_more(page):
    """Click 'Toon meer producten' button."""
    try:
        # Look for the specific button
        button = page.query_selector("button:has-text('Toon meer producten')")
        if not button:
            button = page.query_selector("a:has-text('Toon meer producten')")

        if button and button.is_visible():
            print(f"   🔘 Found 'Toon meer producten' button")

            # Scroll to button naturally
            button.scroll_into_view_if_needed()
            random_delay(0.5, 1)

            # Human-like click
            button.click()
            print(f"   ✅ Clicked button")
            return True
    except Exception as e:
        print(f"   ⚠️ Click error: {e}")

    return False


def load_all_products(page, product_selector):
    """Load all products by clicking 'Load More' button."""
    print("⬇️ Loading all products (human-like)...")

    previous_count = 0
    no_change_count = 0
    iteration = 0
    max_no_change = 3

    while True:
        iteration += 1

        # Scroll down naturally to find the button
        for _ in range(3):
            human_scroll(page)

        random_delay(1, 2)

        # Try to click "Load More" button
        button_clicked = click_load_more(page)

        if button_clicked:
            print(f"   ⏳ Waiting for products...")
            random_delay(2, 4)  # Human-like wait
        else:
            # No button, scroll more
            for _ in range(2):
                human_scroll(page)
            random_delay(1, 2)

        # Count products
        current_count = page.evaluate(f"document.querySelectorAll('{product_selector}').length")

        print(f"   Iteration #{iteration}: {current_count} products", end="")

        if current_count > previous_count:
            new_items = current_count - previous_count
            print(f" (+{new_items} new)")
            no_change_count = 0
        else:
            no_change_count += 1
            print(f" (no change {no_change_count}/{max_no_change})")

        previous_count = current_count

        if no_change_count >= max_no_change:
            print(f"🛑 Finished loading.")
            break

        if iteration > 100:
            print("⚠️ Max iterations reached")
            break

        # Random pause between iterations
        random_delay(0.5, 1.5)

    return current_count


def scrape_promotions():
    print("🚀 Starting Carrefour scraper (stealth mode)...")
    promotions = []

    with sync_playwright() as p:
        # Launch with stealth settings
        browser = p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
            ]
        )

        context = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
            viewport={"width": 1366, "height": 768},
            locale="nl-BE",
            timezone_id="Europe/Brussels",
        )

        # Remove webdriver property
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        page = context.new_page()

        # Navigate
        print(f"🌍 Navigating to Carrefour...")
        page.goto(CARREFOUR_URL, wait_until="domcontentloaded", timeout=60000)

        random_delay(3, 5)  # Let page fully load

        # Handle cookies
        handle_cookie_consent(page)
        random_delay(2, 3)

        # Wait for products
        print("⏳ Waiting for products...")

        product_selector = ".product-tile"
        try:
            page.wait_for_selector(product_selector, timeout=15000)
            initial_count = len(page.query_selector_all(product_selector))
            print(f"   ✅ Found {initial_count} initial products")
        except Exception:
            print("⚠️ Products not found. Saving debug...")
            page.screenshot(path="debug_screenshot.png")
            browser.close()
            return []

        # Load all products
        total_products = load_all_products(page, product_selector)
        print(f"📊 Total products: {total_products}")

        # Extract data
        cards = page.query_selector_all(product_selector)
        print(f"👀 Extracting {len(cards)} products...")

        for i, card in enumerate(cards):
            try:
                brand_el = card.query_selector(".brand-wrapper a")
                brand = brand_el.inner_text().strip() if brand_el else ""

                title_el = card.query_selector(".name-wrapper .desktop-name, .name-wrapper .link")
                raw_title = title_el.inner_text().strip() if title_el else ""
                full_title = f"{brand} {raw_title}".strip()

                if not full_title:
                    continue

                promo_el = card.query_selector(".promo-tag-text")
                offer = promo_el.inner_text().strip() if promo_el else ""

                date_el = card.query_selector(".promo-validity-date")
                raw_date = date_el.text_content().strip() if date_el else ""
                valid_until = parse_date(raw_date)

                link_el = card.query_selector(".image-container a")
                product_path = link_el.get_attribute("href") if link_el else ""
                product_url = BASE_URL + product_path if product_path.startswith("/") else product_path

                img_el = card.query_selector(".image-container img")
                image_url = img_el.get_attribute("src") if img_el else ""

                promotions.append({
                    "title": full_title,
                    "offer_details": offer,
                    "valid_until": valid_until,
                    "product_url": product_url,
                    "image_url": image_url,
                    "scraped_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                })

                if (i + 1) % 100 == 0:
                    print(f"   Processed {i + 1}/{len(cards)}...")

            except Exception:
                continue

        browser.close()

    return promotions


if __name__ == "__main__":
    data = scrape_promotions()

    if data:
        df = pd.DataFrame(data)
        df['title'] = df['title'].str.replace('\n', ' ', regex=False)
        df['title'] = df['title'].str.replace(r'\s+', ' ', regex=True)
        df = df.drop_duplicates(subset=['title', 'product_url'], keep='first')

        df.to_csv(OUTPUT_FILE, index=False, encoding='utf-8-sig')
        print(f"\n✅ Saved {len(df)} items to '{OUTPUT_FILE}'")
        print(df.head(10).to_string())
    else:
        print("❌ No data found.")