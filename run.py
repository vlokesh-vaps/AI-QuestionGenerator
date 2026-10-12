import os
import uvicorn
from app.core.config import settings

if __name__ == "__main__":
    host = os.getenv("HOST", "127.0.0.1")
    port = int(os.getenv("PORT", "8050"))
    reload = os.getenv("DEBUG", "True").lower() in ["true", "1", "yes"]

    prefix = settings.APPLICATION_ROOT
    base_url = f"http://{host}:{port}{prefix}"
    print(f"🚀 Starting AI Question Generator on {base_url}")
    print(f"📖 Swagger UI available at {base_url}/docs")

    uvicorn.run("app.main:app", host=host, port=port, reload=reload)
