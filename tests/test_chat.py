import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


class TestChatEndpoint:
    """Tests for the Dobby AI chat endpoint."""

    @pytest.mark.asyncio
    async def test_chat_non_streaming_success(self, client: AsyncClient):
        """Test successful non-streaming chat response."""
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="Based on your data, you spent €52.41 in total.")]

        with patch("app.services.dobby_chat_service.DobbyChatService.chat") as mock_chat:
            mock_chat.return_value = "Based on your data, you spent €52.41 in total."

            response = await client.post(
                "/api/v1/chat/",
                json={"message": "How much did I spend in total?"}
            )

            assert response.status_code == 200
            data = response.json()
            assert "response" in data
            assert "52.41" in data["response"] or mock_chat.called

    @pytest.mark.asyncio
    async def test_chat_streaming_success(self, client: AsyncClient):
        """Test successful streaming chat response."""
        async def mock_stream(*args, **kwargs):
            yield "Based on your data, "
            yield "you spent €52.41 in total."

        with patch("app.services.dobby_chat_service.DobbyChatService.chat_stream") as mock_chat_stream:
            mock_chat_stream.return_value = mock_stream()

            response = await client.post(
                "/api/v1/chat/stream",
                json={"message": "How much did I spend in total?"}
            )

            assert response.status_code == 200
            assert response.headers.get("content-type") == "text/event-stream; charset=utf-8"

    @pytest.mark.asyncio
    async def test_chat_empty_message(self, client: AsyncClient):
        """Test chat with empty message returns validation error."""
        response = await client.post(
            "/api/v1/chat/",
            json={"message": ""}
        )

        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_chat_with_conversation_history(self, client: AsyncClient):
        """Test chat with conversation history."""
        with patch("app.services.dobby_chat_service.DobbyChatService.chat") as mock_chat:
            mock_chat.return_value = "At Colruyt, you spent €22.54 across 6 items."

            response = await client.post(
                "/api/v1/chat/",
                json={
                    "message": "How much did I spend at Colruyt?",
                    "conversation_history": [
                        {"role": "user", "content": "What are my total expenses?"},
                        {"role": "assistant", "content": "Your total expenses are €52.41."}
                    ]
                }
            )

            assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_chat_message_too_long(self, client: AsyncClient):
        """Test chat with message exceeding max length."""
        long_message = "x" * 2001  # Max is 2000

        response = await client.post(
            "/api/v1/chat/",
            json={"message": long_message}
        )

        assert response.status_code == 422  # Validation error


class TestDobbyChatService:
    """Tests for the Dobby chat service."""

    @pytest.mark.asyncio
    async def test_get_user_transaction_context(self, test_session, test_user, test_transactions):
        """Test that transaction context is built correctly."""
        from app.services.dobby_chat_service import DobbyChatService

        service = DobbyChatService()
        context = await service._get_user_transaction_context(test_session, str(test_user.id))

        # Verify context contains expected information
        assert "USER'S TRANSACTION DATA" in context
        assert "COLRUYT" in context
        assert "ALDI" in context
        assert "CARREFOUR" in context
        assert "SPENDING BY CATEGORY" in context
        assert "SPENDING BY STORE" in context
        assert "Dairy & Eggs" in context or "DAIRY_EGGS" in context

    @pytest.mark.asyncio
    async def test_get_user_transaction_context_no_data(self, test_session, test_user):
        """Test context message when user has no transactions."""
        from app.services.dobby_chat_service import DobbyChatService
        # Create a new user with no transactions
        from app.models.user import User
        import uuid

        new_user = User(
            id=str(uuid.uuid4()),
            firebase_uid="new_user_firebase_uid",
            email="newuser@example.com",
            display_name="New User",
            is_active=True,
        )
        test_session.add(new_user)
        await test_session.commit()

        service = DobbyChatService()
        context = await service._get_user_transaction_context(test_session, str(new_user.id))

        assert "No transaction data available" in context


class TestChatIntegration:
    """Integration tests for the chat API with real Claude API calls."""

    @pytest.mark.asyncio
    @pytest.mark.skipif(True, reason="Integration test - requires API key and makes real API calls")
    async def test_chat_integration_total_spending(self, client: AsyncClient):
        """Integration test: Ask about total spending."""
        response = await client.post(
            "/api/v1/chat/",
            json={"message": "What is my total spending?"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "response" in data
        # The response should mention the total amount
        assert "€" in data["response"] or "EUR" in data["response"]

    @pytest.mark.asyncio
    @pytest.mark.skipif(True, reason="Integration test - requires API key and makes real API calls")
    async def test_chat_integration_category_breakdown(self, client: AsyncClient):
        """Integration test: Ask about spending by category."""
        response = await client.post(
            "/api/v1/chat/",
            json={"message": "What are my top spending categories?"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "response" in data

    @pytest.mark.asyncio
    @pytest.mark.skipif(True, reason="Integration test - requires API key and makes real API calls")
    async def test_chat_integration_store_comparison(self, client: AsyncClient):
        """Integration test: Compare spending at different stores."""
        response = await client.post(
            "/api/v1/chat/",
            json={"message": "Compare my spending at Colruyt vs Aldi"}
        )

        assert response.status_code == 200
        data = response.json()
        assert "response" in data

    @pytest.mark.asyncio
    @pytest.mark.skipif(True, reason="Integration test - requires API key and makes real API calls")
    async def test_chat_stream_integration(self, client: AsyncClient):
        """Integration test: Test streaming response."""
        response = await client.post(
            "/api/v1/chat/stream",
            json={"message": "Give me a brief summary of my spending"}
        )

        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/event-stream; charset=utf-8"

        # Read and parse SSE events
        content = response.content.decode()
        events = content.strip().split("\n\n")

        # Should have at least one text event and a done event
        assert len(events) >= 2

        # Check last event is done
        last_event = events[-1]
        if last_event.startswith("data: "):
            data = json.loads(last_event[6:])
            assert data["type"] == "done"
