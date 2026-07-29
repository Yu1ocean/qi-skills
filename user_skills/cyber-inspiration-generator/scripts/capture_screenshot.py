#!/usr/bin/env python3
import argparse
import sys

def main():
    parser = argparse.ArgumentParser(description="Capture a full-page screenshot for a given URL.")
    parser.add_argument("--url", required=True, help="Target URL (deployed page url)")
    parser.add_argument("--output", required=True, help="Output image path, e.g. outputs/fullpage.png")
    parser.add_argument("--width", type=int, default=1440, help="Viewport width")
    parser.add_argument("--height", type=int, default=900, help="Viewport height")
    parser.add_argument("--wait_ms", type=int, default=1200, help="Extra wait time after load")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print("Playwright is not available. Install it first: pip install playwright && playwright install chromium", file=sys.stderr)
        raise

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": args.width, "height": args.height})
        page.goto(args.url, wait_until="networkidle")
        if args.wait_ms > 0:
            page.wait_for_timeout(args.wait_ms)
        page.screenshot(path=args.output, full_page=True)
        browser.close()

    print(f"✅ Screenshot saved: {args.output}")

if __name__ == "__main__":
    main()
