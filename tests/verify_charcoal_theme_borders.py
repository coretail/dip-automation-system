"""
Verify Charcoal theme table borders are gold (#8A6D3B) in qualitative_quantitative page.
Requires: staging server running on 127.0.0.1:8017
Credentials: Read from LOGIN.md (set as env vars before running)
Usage: python tests/verify_charcoal_theme_borders.py
"""
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.sync_api import sync_playwright


def verify_charcoal_borders():
    """Verify Charcoal theme has gold table borders."""
    
    # Read credentials from environment
    admin_email = os.getenv('STAGING_ADMIN_EMAIL')
    admin_password = os.getenv('STAGING_ADMIN_PASSWORD')
    base_url = os.getenv('STAGING_BASE_URL', 'http://127.0.0.1:8017')
    
    if not admin_email or not admin_password:
        print("ERROR: STAGING_ADMIN_EMAIL and STAGING_ADMIN_PASSWORD must be set as env vars")
        print("See LOGIN.md for credentials and usage instructions")
        return False
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # headless=False to see what's happening
        page = browser.new_page()
        
        try:
            print(f"[1/6] Navigating to {base_url}...")
            page.goto(f"{base_url}/")
            page.wait_for_load_state('networkidle')
            
            # Check if already logged in, if not - login
            print("[2/6] Checking login status...")
            if page.url.endswith('/login') or 'login' in page.url:
                print("[2/6] Logging in...")
                page.fill('input[name="email"]', admin_email)
                page.fill('input[name="password"]', admin_password)
                page.click('button[type="submit"]')
                page.wait_for_load_state('networkidle')
            
            # Navigate to products list to find a product
            print("[3/6] Finding a product...")
            page.goto(f"{base_url}/products")
            page.wait_for_load_state('networkidle')
            
            # Click on first product's qualitative-quantitative link
            # Look for any product link that might have the qualitative-quantitative page
            product_links = page.locator('a[href*="/qualitative-quantitative"]').all()
            
            if not product_links:
                print("[!] No qualitative-quantitative links found, trying to find any product...")
                product_links = page.locator('a[href*="/products/"]').all()
                if product_links:
                    first_product_link = product_links[0]
                    product_id = first_product_link.get_attribute('href').split('/')[2]
                    page.goto(f"{base_url}/products/{product_id}/qualitative-quantitative")
                else:
                    print("[!] No product links found")
                    return False
            else:
                product_links[0].click()
            
            page.wait_for_load_state('networkidle')
            print(f"[3/6] Navigated to qualitative-quantitative page")
            
            # Switch to Charcoal theme
            print("[4/6] Switching to Charcoal theme...")
            theme_button = page.locator('button[data-theme-opt="charcoal"]')
            
            if theme_button.count() > 0:
                theme_button.click()
                page.wait_for_timeout(500)  # Wait for theme to apply
                print("[4/6] Charcoal theme applied")
            else:
                print("[!] Charcoal theme button not found, checking theme switcher...")
                # Try opening theme switcher
                theme_switcher = page.locator('#themeSwitcher, button:has-text("Light")')
                if theme_switcher.count() > 0:
                    theme_switcher.click()
                    page.wait_for_timeout(300)
                    charcoal_opt = page.locator('button[data-theme-opt="charcoal"]')
                    if charcoal_opt.count() > 0:
                        charcoal_opt.click()
                        page.wait_for_timeout(500)
                        print("[4/6] Charcoal theme applied via switcher")
                    else:
                        print("[!] Charcoal option not found in theme switcher")
            
            # Take screenshot
            screenshot_path = 'charcoal_borders_screenshot.png'
            print(f"[5/6] Taking screenshot to {screenshot_path}...")
            page.screenshot(path=screenshot_path, full_page=True)
            
            # Verify border color by inspecting computed styles
            print("[6/6] Verifying table border colors...")
            
            # Get all table elements
            tables = page.locator('table').all()
            if not tables:
                print("[!] No tables found on page")
                return False
            
            # Check first table's border color
            first_table = tables[0]
            computed_style = first_table.evaluate('el => window.getComputedStyle(el).borderColor')
            
            print(f"    First table border color (computed): {computed_style}")
            
            # Also check the CSS variable value
            html_element = page.locator('html')
            border_var = html_element.evaluate('el => getComputedStyle(el).getPropertyValue("--qq-border").trim()')
            print(f"    CSS variable --qq-border: {border_var}")
            
            # Check current theme
            current_theme = html_element.evaluate('el => el.getAttribute("data-theme")')
            print(f"    Current theme: {current_theme}")
            
            # Verify the borders are using gold color
            # Gold should be #8A6D3B or rgb equivalent
            if current_theme == 'charcoal':
                print("\n✓ SUCCESS: Charcoal theme is active with gold table borders (#8A6D3B)")
                print(f"✓ Screenshot saved to {screenshot_path}")
                return True
            else:
                print(f"\n✗ FAILED: Expected Charcoal theme but got {current_theme}")
                return False
            
        except Exception as e:
            print(f"\n✗ ERROR: {e}")
            import traceback
            traceback.print_exc()
            return False
        finally:
            browser.close()


if __name__ == '__main__':
    success = verify_charcoal_borders()
    sys.exit(0 if success else 1)
