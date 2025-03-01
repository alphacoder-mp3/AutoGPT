import logging
from typing import Any, Dict, Optional

import aiohttp
from autogpt_libs.auth.middleware import auth_middleware
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.data import graph as graph_db
from backend.data.block import get_block
from backend.data.user import get_user_by_id
from backend.server.utils import get_user_id
from backend.util.settings import Settings

logger = logging.getLogger(__name__)
settings = Settings()

OTTO_API_URL = settings.config.otto_api_url

router = APIRouter()


class Document(BaseModel):
    url: str
    relevance_score: float


class ApiResponse(BaseModel):
    answer: str
    documents: list[Document]
    success: bool


class GraphData(BaseModel):
    nodes: list[Dict[str, Any]]
    edges: list[Dict[str, Any]]


class Message(BaseModel):
    query: str
    response: str


class ChatRequest(BaseModel):
    query: str
    conversation_history: list[Message]
    message_id: str
    include_graph_data: bool = False
    graph_id: Optional[str] = None


async def fetch_graph_data(request, user_id):
    """Fetch graph data if requested and available."""
    if not (request.include_graph_data and request.graph_id):
        return None

    try:
        graph = await graph_db.get_graph(request.graph_id, user_id=user_id)
        if not graph:
            return None

        nodes_data = []
        for node in graph.nodes:
            block = get_block(node.block_id)
            if not block:
                continue

            node_data = {
                "id": node.id,
                "block_id": node.block_id,
                "block_name": block.name,
                "block_type": (
                    block.block_type.value if hasattr(block, "block_type") else None
                ),
                "data": {
                    k: v
                    for k, v in (node.input_default or {}).items()
                    if k not in ["credentials"]  # Exclude sensitive data
                },
            }
            nodes_data.append(node_data)

        return {
            "nodes": nodes_data,
            "graph_name": graph.name,
            "graph_description": graph.description,
        }
    except Exception as e:
        logger.error(f"Failed to fetch graph data: {str(e)}")
        return None


@router.post(
    "/ask", response_model=ApiResponse, dependencies=[Depends(auth_middleware)]
)
async def proxy_otto_request(
    request: ChatRequest, user_id: str = Depends(get_user_id)
) -> ApiResponse:
    """
    Proxy requests to Otto API while adding necessary security headers and logging.
    Requires an authenticated user.
    """
    try:
        async with aiohttp.ClientSession() as session:
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json",
            }

            # If graph data is requested, fetch it
            graph_data = await fetch_graph_data(request, user_id)

            # Prepare the payload with optional graph data
            payload = {
                "query": request.query,
                "conversation_history": [
                    msg.dict() for msg in request.conversation_history
                ],
                "message_id": request.message_id,
            }

            if graph_data:
                payload["graph_data"] = graph_data

            logger.info(f"Sending request to Otto API for user {user_id}")
            logger.debug(f"Request payload: {payload}")

            async with session.post(
                OTTO_API_URL, json=payload, headers=headers
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Otto API error: {error_text}")
                    raise HTTPException(
                        status_code=response.status,
                        detail=f"Otto API request failed: {error_text}",
                    )

                data = await response.json()
                logger.info(
                    f"Successfully received response from Otto API for user {user_id}"
                )
                return ApiResponse(**data)

    except aiohttp.ClientError as e:
        logger.error(f"Connection error to Otto API: {str(e)}")
        raise HTTPException(status_code=503, detail="Failed to connect to Otto service")
    except Exception as e:
        logger.error(f"Unexpected error in Otto API proxy: {str(e)}")
        raise HTTPException(
            status_code=500, detail="Internal server error in Otto proxy"
        )
