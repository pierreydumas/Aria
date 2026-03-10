"""
E2E browser tests — Playwright against running Docker services (S-30).

Prerequisites:
    pip install pytest-playwright
    playwright install chromium
    docker compose up -d

Run:
    pytest tests/e2e/test_chat_flow.py -v --timeout=120
"""
import os
import re

import pytest
from playwright.sync_api import Page, expect

BASE_URL = os.environ.get("ARIA_WEB_URL", "http://localhost:5050")


# ── Page load tests ──────────────────────────────────────────────────────────


def test_home_page_loads(page: Page):
    """Home page loads and has a nav bar."""
    page.goto(BASE_URL)
    expect(page).to_have_title(re.compile(r"Aria", re.IGNORECASE))
    expect(page.locator("nav")).to_be_visible()


def test_chat_page_loads(page: Page):
    """Chat page renders the message input area."""
    page.goto(f"{BASE_URL}/chat")
    # Page should contain an input area for messages
    input_area = page.locator("textarea, input[type='text'], [contenteditable]").first
    expect(input_area).to_be_visible(timeout=10000)


def test_engine_operations_loads(page: Page):
    """Engine operations dashboard loads without JS errors."""
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(f"{BASE_URL}/engine/operations")
    expect(page.locator("h1, h2, .page-header, .page-title").first).to_be_visible(
        timeout=10000
    )
    page.wait_for_timeout(2000)
    assert len(errors) == 0, f"JavaScript errors on /engine/operations: {errors}"


# ── Navigation tests ─────────────────────────────────────────────────────────


def test_navigation_no_500_errors(page: Page):
    """All major nav links should return status < 500."""
    page.goto(BASE_URL)
    nav_links = page.locator("nav a[href]").all()

    visited: set[str] = set()
    failures: list[str] = []

    for link in nav_links:
        href = link.get_attribute("href")
        if not href or not href.startswith("/") or href in visited:
            continue
        # Skip external links and API endpoints
        if href.startswith("/api/") or href.startswith("/graphql"):
            continue
        visited.add(href)
        response = page.goto(f"{BASE_URL}{href}")
        if response and response.status >= 500:
            failures.append(f"{href} → {response.status}")

    assert not failures, f"Pages returned 500+: {failures}"


# ── Chat flow tests ──────────────────────────────────────────────────────────


@pytest.mark.slow
def test_chat_send_message(page: Page):
    """Full flow: open chat, type message, send, and see a response appear."""
    page.goto(f"{BASE_URL}/chat")

    # Find the message input
    input_field = page.locator("textarea, input[type='text']").first
    expect(input_field).to_be_visible(timeout=10000)
    input_field.fill("Hello Aria, this is an E2E test")

    # Click send
    send_btn = page.locator(
        "button:has-text('Send'), button[type='submit'], button.send-btn"
    ).first
    send_btn.click()

    # Wait for a response message to appear (streaming may take time)
    response_area = page.locator(
        ".message.assistant, .response, .chat-message.assistant, .bot-message"
    ).last
    expect(response_area).to_be_visible(timeout=60000)

    response_text = response_area.text_content()
    assert response_text and len(response_text.strip()) > 0, "Chat response was empty"


# ── Dashboard data loading tests ─────────────────────────────────────────────


def test_skill_health_dashboard_loads_data(page: Page):
    """Skill health page fetches data from API without errors."""
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(f"{BASE_URL}/skill-health")

    # Wait for the JS to fetch and render data (or show empty state)
    page.wait_for_timeout(3000)

    # Should have either skill cards or an empty-state message
    has_cards = page.locator(".health-card").count() > 0
    has_empty = page.locator(".empty-state").count() > 0
    assert has_cards or has_empty, "Skill health page didn't load data or show empty state"

    assert len(errors) == 0, f"JavaScript errors on /skill-health: {errors}"


def test_model_manager_loads(page: Page):
    """Model manager page renders the model list."""
    page.goto(f"{BASE_URL}/model-manager")
    # Should load the model list or table container
    page.wait_for_timeout(3000)
    body_text = page.locator("body").text_content()
    assert body_text and len(body_text.strip()) > 100, "Model manager page appears empty"


def test_task_queue_manager_loads(page: Page):
    """Task queue manager page renders the queue management UI."""
    page.goto(f"{BASE_URL}/task-queue")
    page.wait_for_timeout(3000)
    body_text = page.locator("body").text_content()
    assert body_text and len(body_text.strip()) > 100, "Task queue manager page appears empty"


def test_sentiment_page_loads(page: Page):
    """Sentiment dashboard loads without error."""
    errors: list[str] = []
    page.on("pageerror", lambda e: errors.append(str(e)))

    page.goto(f"{BASE_URL}/sentiment")
    page.wait_for_timeout(3000)

    assert len(errors) == 0, f"JavaScript errors on /sentiment: {errors}"
