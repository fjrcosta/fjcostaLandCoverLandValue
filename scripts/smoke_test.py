#!/usr/bin/env python3
"""Headless smoke test of the portal: exercise every control and record JavaScript errors."""

import argparse
import re
import time

from playwright.sync_api import Page, sync_playwright


class Report:
    def __init__(self) -> None:
        self.rows: list[tuple[str, bool, str]] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        self.rows.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name}{'  — ' + detail if detail else ''}", flush=True)


def settle(page: Page, seconds: float) -> None:
    page.wait_for_timeout(int(seconds * 1000))


def visible(page: Page, selector: str) -> bool:
    return page.locator(selector).is_visible()


def run(base_url: str, with_reach: bool, report: Report) -> list[str]:
    errors: list[str] = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(args=["--use-angle=swiftshader", "--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"])
        page = browser.new_page(viewport={"width": 1600, "height": 1000}, accept_downloads=True)
        page.on("pageerror", lambda exc: errors.append(f"pageerror: {exc}"))
        page.on("console", lambda msg: errors.append(f"console.{msg.type}: {msg.text}") if msg.type == "error" else None)

        page.goto(f"{base_url}/", wait_until="load")
        report.check("landing loads", page.locator("h1").count() == 1, page.locator("h1").inner_text().replace("\n", " "))
        report.check("landing links to map", page.locator('a[href="map3d/"]').count() == 1)
        if with_reach:
            report.check("landing reachability table", page.locator("table.reach-table tbody tr").count() == 3)

        page.goto(f"{base_url}/map3d/", wait_until="load")
        page.wait_for_selector("#loadingOverlay.done", timeout=90_000)
        settle(page, 4)
        report.check("map initialises", not visible(page, "#errorBanner"), page.locator("#errorBanner").inner_text() if visible(page, "#errorBanner") else "")
        report.check("municipality options", page.locator("#citySelect option").count() == 13)
        report.check("class filters", page.locator("#classFilters input").count() == 10)
        report.check("road filters", page.locator("#roadFilters input").count() == 5)

        for dim in ["coverDimension", "valueDimension", "transportDimension"]:
            page.check(f"#{dim}")
            settle(page, 1.5)
        report.check("cover+value+transport on", page.locator("#classStatisticsBody tr").count() == 10)
        report.check("combined statistics mode", page.get_attribute(".class-statistics", "data-statistics-mode") == "combined")

        page.locator("#toggleClasses").click()
        settle(page, 0.5)
        report.check("clear classes", page.locator("#classFilters input:checked").count() == 0)
        page.locator("#toggleClasses").click()
        page.locator("#toggleRoadClasses").click()
        page.locator("#toggleRoadClasses").click()
        settle(page, 0.5)
        report.check("select all classes/roads", page.locator("#classFilters input:checked").count() == 10 and page.locator("#roadFilters input:checked").count() == 5)

        page.fill("#heightScale", "2")
        page.dispatch_event("#heightScale", "input")
        for tint in ["valueTint", "coverTint", "transportTint"]:
            page.fill(f"#{tint}", "0.6")
            page.dispatch_event(f"#{tint}", "input")
        settle(page, 1)
        report.check("sliders", page.locator("#heightScaleOutput").inner_text() == "2.00×")

        page.select_option("#citySelect", "maringa")
        settle(page, 4)
        report.check("select municipality", page.locator("#selectionTitle").inner_text().strip() != "")
        page.select_option("#citySelect", "all")
        settle(page, 3)

        page.check("#ludDimension")
        settle(page, 2)
        report.check("LUD switches panel", visible(page, "#economicsInsightContent") and not page.is_checked("#coverDimension"))
        report.check("LUD ranking 12", page.locator("#economicsRanking li").count() == 12)
        page.check("#lvyDimension")
        settle(page, 1.5)
        report.check("LVY exclusive with LUD", page.is_checked("#lvyDimension") and not page.is_checked("#ludDimension"))
        page.uncheck("#lvyDimension")
        settle(page, 1)
        report.check("economics off restores panel", not visible(page, "#economicsInsightContent"))

        page.check("#coverDimension")
        page.check("#valueDimension")
        settle(page, 1.5)
        page.select_option("#basemapSelect", "satellite")
        settle(page, 2)
        page.select_option("#basemapSelect", "map")
        for toggle in ["buildingsToggle", "buildingsToggle", "perimeterToggle", "perimeterToggle"]:
            page.locator(f"label:has(#{toggle})").click()
            settle(page, 1)
        report.check("basemap/buildings/perimeter toggles", not page.is_checked("#buildingsToggle") and page.is_checked("#perimeterToggle"))

        page.locator("#panelsToggle").click()
        settle(page, 0.8)
        report.check("hide panels", page.locator("#panelsToggle").inner_text() == "Show panels")
        page.locator("#panelsToggle").click()

        report.check("export button stays hidden (as published)", not visible(page, "#downloadButton"))

        page.locator("#aboutButton").click()
        settle(page, 0.5)
        report.check("method dialog opens", page.locator("#aboutDialog").evaluate("d => d.open"))
        page.locator(".dialog-close").click()

        page.locator("#tourButton").click()
        settle(page, 2)
        report.check("tour starts", "Stop" in page.locator("#tourButton").inner_text())
        page.locator("#tourButton").click()
        report.check("tour stops", "tour" in page.locator("#tourButton").inner_text())

        page.locator("#resetButton").click()
        settle(page, 2.5)
        page.mouse.click(800, 520)
        settle(page, 2)
        report.check("map click places analytical marker", page.locator(".maplibregl-marker").count() >= 1)
        page.locator("#resetButton").click()
        settle(page, 2)

        if with_reach:
            page.check("#reachDimension")
            page.wait_for_function("document.querySelector('#reachStatus').textContent.startsWith('Click')", timeout=60_000)
            settle(page, 3)
            report.check("reachability loads, flies to Londrina", page.input_value("#citySelect") == "londrina")
            page.mouse.click(800, 520)
            page.wait_for_function("document.querySelector('#reachStatus').textContent.startsWith('Origin')", timeout=30_000)
            status = page.locator("#reachStatus").inner_text()
            ms = int(re.search(r"computed in (\d+) ms", status).group(1))
            report.check("reachability computes 3 modes", page.locator("#reachSummary tbody tr").count() == 3, f"{ms} ms in Chromium")
            summary_rows = [r.inner_text().replace("\t", " ") for r in page.locator("#reachSummary tbody tr").all()]
            print("      " + " | ".join(summary_rows))
            for mode in ["car", "bus", "walk"]:
                page.select_option("#reachMode", mode)
                settle(page, 1)
            report.check("mode switching", page.locator("#reachSummary tr.is-active td").first.inner_text() == "Walking")
            page.mouse.click(700, 600)
            page.wait_for_function("!document.querySelector('#reachStatus').textContent.includes('%s')" % status[:30], timeout=30_000)
            report.check("second origin", True, re.search(r"computed in (\d+) ms", page.locator("#reachStatus").inner_text()).group(0))
            page.check("#coverDimension")
            settle(page, 1.5)
            hover = ""
            for x, y in [(x, y) for y in range(300, 900, 60) for x in range(450, 1250, 80)]:
                page.mouse.move(x, y)
                settle(page, 0.15)
                if visible(page, "#hoverCard"):
                    hover = page.locator("#hoverCard").inner_text()
                    break
            report.check("hover shows travel time", "travel time from origin" in hover, hover.split("\n")[-1] if hover else "no patch under cursor")
            page.check("#ludDimension")
            settle(page, 1.5)
            report.check("economics deactivates reachability", not page.is_checked("#reachDimension") and not visible(page, "#reachControls"))
            page.uncheck("#ludDimension")
            page.check("#reachDimension")
            page.wait_for_function("document.querySelector('#reachStatus').textContent.startsWith('Click')", timeout=30_000)
            before = page.locator(".maplibregl-marker").count()
            page.mouse.click(800, 520)
            page.wait_for_function("document.querySelector('#reachStatus').textContent.startsWith('Origin')", timeout=30_000)
            with_origin = page.locator(".maplibregl-marker").count()
            page.uncheck("#reachDimension")
            settle(page, 1)
            after = page.locator(".maplibregl-marker").count()
            report.check("reachability off removes marker", with_origin == before + 1 and after == before, f"markers {before} → {with_origin} → {after}")
            page.mouse.click(800, 520)
            settle(page, 1.5)
            report.check("map click back to analytical popup", page.locator(".maplibregl-popup").count() >= 1)

        browser.close()
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--with-reach", action="store_true")
    args = parser.parse_args()
    report = Report()
    started = time.time()
    errors = run(args.url, args.with_reach, report)
    failed = [r for r in report.rows if not r[1]]
    print(f"\n{len(report.rows) - len(failed)}/{len(report.rows)} checks passed in {time.time() - started:.0f} s")
    print(f"JavaScript errors: {len(errors)}")
    for e in errors:
        print("  " + e[:300])


if __name__ == "__main__":
    main()
