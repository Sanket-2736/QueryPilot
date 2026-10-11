"""FastAPI application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api import chat, conversations, eval as eval_api
from app.observability import setup_langfuse


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="QueryPilot",
        description="Stateful text-to-SQL agent",
        version="0.1.0",
        debug=settings.debug,
    )

    # Setup observability (Langfuse)
    setup_langfuse()

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include routers
    app.include_router(chat.router, prefix="/chat", tags=["chat"])
    app.include_router(conversations.router, prefix="/conversations", tags=["conversations"])
    app.include_router(eval_api.router, prefix="/eval", tags=["eval"])

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        """Health check endpoint."""
        return {"status": "ok"}

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.api_host, port=settings.api_port)
