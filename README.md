# Try-On Shop (Perfect Corp cloth-v4 test store)

## Run (Ubuntu / WSL)
    unzip tryon-shop.zip && cd tryon-shop
    ./run.sh          # first run creates .venv and .env, then stops
    nano .env         # set PERFECT_API_KEY, ADMIN_PASSWORD (optional PEXELS_API_KEY)
    ./run.sh

- Shop:  http://localhost:8000
- Admin: http://localhost:8000/admin  (any username, password = ADMIN_PASSWORD)

## Adding clothes
Admin > Products: paste an image URL, upload a file, or (with PEXELS_API_KEY) import by search.
Best results: one garment, front-facing product shot. Set the category (upper_body, lower_body, full_body) when you know it.
Pinterest is not supported (its terms forbid scraping). Only use images you have the right to use.

## What is recorded
Per try-on: visitor cookie ID, IP, browser, product, uploaded photo, result image, status and error, task ID,
seconds (upload + generation), thumbs up/down and comment. Everything is in data/ (shop.db + images).
Each visitor is capped by MAX_TRYONS_PER_VISITOR to protect your credits.

## Notes
Photos of real people are stored: keep the consent checkbox, and delete data/ when the test ends.
