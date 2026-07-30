from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from app.services.assets import static_asset_version

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_static_asset_version_changes_with_asset_contents(tmp_path: Path) -> None:
    (tmp_path / "app.js").write_text("first", encoding="utf-8")
    (tmp_path / "styles.css").write_text("styles", encoding="utf-8")
    first = static_asset_version(tmp_path)

    (tmp_path / "app.js").write_text("second", encoding="utf-8")

    assert static_asset_version(tmp_path) != first


def test_page_uses_versioned_stylesheet_and_script_urls() -> None:
    environment = Environment(
        loader=FileSystemLoader(PROJECT_ROOT / "app" / "templates"),
        autoescape=True,
    )
    environment.globals["url_for"] = lambda _name, path: f"/static{path}"
    environment.globals["static_version"] = "asset-hash"

    html = environment.get_template("index.html").render()

    assert '/static/styles.css?v=asset-hash"' in html
    assert '/static/app.js?v=asset-hash"' in html


def test_page_starts_with_an_empty_search_and_resettable_rate_meter() -> None:
    environment = Environment(
        loader=FileSystemLoader(PROJECT_ROOT / "app" / "templates"),
        autoescape=True,
    )
    environment.globals["url_for"] = lambda _name, path: f"/static{path}"
    environment.globals["static_version"] = "asset-hash"

    html = environment.get_template("index.html").render()

    assert "Enter a search to browse the index." in html
    assert 'class="pagination hidden" id="results-pagination"' in html
    assert 'id="scan-rate-reset"' in html
