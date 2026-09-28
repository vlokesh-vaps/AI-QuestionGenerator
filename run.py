import uvicorn
import os

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("DEBUG", "True").lower() in ["true", "1", "yes"]

    print(f"🚀 Starting AI Question Generator on http://{host}:{port}")
    print(f"📖 Swagger UI available at http://{host}:{port}/docs")

    uvicorn.run("app.main:app", host=host, port=port, reload=reload)
