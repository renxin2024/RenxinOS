import os

import uvicorn


def main() -> None:
    host = os.getenv("RENXINOS_HOST", "127.0.0.1")
    port = int(os.getenv("RENXINOS_PORT", "8000"))
    print(f"Renxin OS API → http://{host}:{port}")
    print(f"API 调试文档 → http://{host}:{port}/scalar")
    uvicorn.run("src.api:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
