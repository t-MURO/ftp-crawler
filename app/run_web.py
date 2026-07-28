import uvicorn

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.web_host,
        port=settings.web_port,
        workers=settings.web_workers,
        proxy_headers=True,
        forwarded_allow_ips="*",
        access_log=True,
    )


if __name__ == "__main__":
    main()
