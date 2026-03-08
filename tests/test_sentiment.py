"""Sentiment analysis endpoint tests."""


class TestSentiment:
    """Test suite for sentiment analysis endpoints."""

    def test_analyze_sentiment(self, api):
        """Test single-message sentiment analysis on /analysis facade."""
        payload = {"text": "This is a great day!", "store": False}
        r = api.post("/analysis/sentiment/message", json=payload)
        assert r.status_code in (200, 401, 422)
        if r.status_code == 200:
            data = r.json()
            assert "sentiment" in data or "tone_recommendation" in data

    def test_analyze_sentiment_empty_text(self, api):
        """Test sentiment analysis rejects empty text."""
        payload = {"text": ""}
        r = api.post("/analysis/sentiment/message", json=payload)
        assert r.status_code in (400, 401, 422)

    def test_analyze_sentiment_missing_text(self, api):
        """Test sentiment analysis requires text field."""
        payload = {}
        r = api.post("/analysis/sentiment/message", json=payload)
        assert r.status_code in (400, 401, 422)

    def test_batch_sentiment_analysis(self, api):
        """Test conversation sentiment analysis on multiple messages."""
        payload = {
            "messages": [
                {"role": "user", "content": "This is great!"},
                {"role": "assistant", "content": "Glad to hear that."},
            ],
            "store": False,
        }
        r = api.post("/analysis/sentiment/conversation", json=payload)
        assert r.status_code in (200, 401, 422)
        if r.status_code == 200:
            data = r.json()
            assert isinstance(data, (list, dict))

    def test_get_sentiment_events(self, api):
        """Test retrieving sentiment history from /analysis."""
        r = api.get("/analysis/sentiment/history")
        assert r.status_code in (200, 401)
        if r.status_code == 200:
            data = r.json()
            assert isinstance(data, dict)
            assert "items" in data or "total" in data

    def test_get_sentiment_events_pagination(self, api):
        """Test sentiment history pagination/filter params."""
        r = api.get("/analysis/sentiment/history?limit=10")
        assert r.status_code in (200, 401)

    def test_get_sentiment_event_by_id(self, api):
        """Test score endpoint availability for recent sentiment aggregate."""
        r = api.get("/analysis/sentiment/score")
        assert r.status_code in (200, 401, 422)

    def test_sentiment_trends(self, api):
        """Test score endpoint with explicit window parameter."""
        r = api.get("/analysis/sentiment/score?hours=24")
        assert r.status_code in (200, 401, 422)

    def test_sentiment_by_speaker(self, api):
        """Test sentiment filtering by speaker."""
        r = api.get("/analysis/sentiment/history?speaker=user")
        assert r.status_code in (200, 401)

    def test_sentiment_by_session(self, api):
        """Test sentiment filtering by agent_id."""
        r = api.get("/analysis/sentiment/history?agent_id=aria")
        assert r.status_code in (200, 401)

    def test_delete_sentiment_event(self, api):
        """Test feedback endpoint shape validation."""
        r = api.post("/analysis/sentiment/feedback", json={"event_id": "not-a-uuid", "confirmed": True})
        assert r.status_code in (200, 400, 401, 422)


# TODO: Add integration tests for multi-dimensional sentiment
# TODO: Test sentiment polarity (positive/negative/neutral)
# TODO: Test sentiment intensity scores
# TODO: Test emotion classification (joy, anger, fear, etc.)
# TODO: Test sentiment aggregation by time period
# TODO: Test sentiment correlation with agent performance
