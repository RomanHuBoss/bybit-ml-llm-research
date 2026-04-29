from __future__ import annotations

from pathlib import Path


def test_project_does_not_contain_bybit_private_order_execution_paths():
    root = Path(__file__).resolve().parents[1]
    forbidden = [
        "/v5/order",
        "create_order",
        "place_order",
        "submit_order",
        "cancel_order",
        "x-bapi-sign",
        "x-bapi-api-key",
        "api_secret",
        "api-secret",
    ]
    scanned = [*Path(root, "app").rglob("*.py"), *Path(root, "frontend").rglob("*")]
    hits: list[str] = []

    for path in scanned:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for marker in forbidden:
            if marker in text:
                hits.append(f"{path.relative_to(root)}: {marker}")

    assert hits == []
