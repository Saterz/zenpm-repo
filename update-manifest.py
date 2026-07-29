import copy
import json
import os
from os import path
from platform import release
from pydoc import resolve
import re
from typing import Any, Literal, NotRequired, Required, TypeAlias, TypedDict

from requests import request

Platform = Literal[
    "koreader",
    "kindle",
    "kobo",
    "android",
    "host",
    "pocketbook",
    "remarkable",
]

Category = Literal[
    "utility",
    "games",
    "productivity",
    "media",
    "theme",
    "patches",
    "fonts",
]

SourceType = Literal[
    "release",
    "source",
]

Architecture = Literal[
    "any",
    "arm",
    "arm64",
    "armv7",
    "x86",
    "x86_64",
    "kindle",
]

JsonPrimitive: TypeAlias = str | int | float | bool | None

JsonValue: TypeAlias = JsonPrimitive | list["JsonValue"] | dict[str, "JsonValue"]


class Repo(TypedDict):
    id: str
    name: str
    url: str
    icon_url: NotRequired[str]


class Asset(TypedDict):
    arch: Architecture | str
    asset: str
    url: str
    size: str


class Package(TypedDict, total=False):
    # Basic metadata
    id: Required[str]
    name: Required[str]
    version: Required[str]
    description: Required[str]
    author: Required[str]
    category: Category
    size: str
    stars: str
    published_at: str

    # Compatibility
    platforms: Required[list[Platform]]
    incompatible_platforms: list[Platform]

    # Package relationships
    dependencies: Required[list[str]]
    conflicts: list[str]

    # Installation scripts
    install_url: str
    uninstall_url: str

    # Package source
    source: str
    source_type: SourceType
    source_asset: str
    source_url: str

    # Release information
    versions_url: str
    readme_url: str
    release_notes_url: str
    prerelease_notes_url: str
    prerelease_version: str

    # Downloadable assets
    assets: list[Asset]
    constraints: dict[str, JsonValue]

    # Images
    icon_url: str
    image_url: str
    images: list[str]
    screenshots: list[str]

    # Featured-package metadata
    featured: bool
    featured_order: int
    featured_image: str


class Manifest(TypedDict):
    schema_version: str
    repo: Repo
    packages: list[Package]


RAW_GITHUB_URL = "https://raw.githubusercontent.com/"
GITHUB_API_URL = "https://api.github.com"
GITHUB_URL = "https://github.com/"

REPO: Repo = {
    "id": "saterz-repo",
    "name": "Saterz's Repository",
    "url": "https://zenpm-repo.saterz.dev",
}

MINIMAL_MANIFEST: Manifest = {
    "schema_version": "1",
    "repo": REPO,
    "packages": [],
}


def request_github(pathname: str):
    headers = {}

    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"

    response = request(
        "GET",
        url=f"{GITHUB_API_URL}/{pathname}",
        headers=headers,
        allow_redirects=True,
        timeout=30,
    )

    response.raise_for_status()

    return response.json()


def normalize_version(name: str) -> str:
    return name.removeprefix("v")


def main():
    manifest: Manifest = copy.deepcopy(MINIMAL_MANIFEST)
    manifest_destination = "manifest.json"

    with open("packages.json", "r", encoding="utf-8") as packages:
        package_configs: list[dict[str, Any]] = json.load(packages)

    for package in package_configs:
        repository = package["repository"]

        repository_details = request_github(f"repos/{repository}")
        release_details = request_github(f"repos/{repository}/releases?per_page=100")

        if not isinstance(repository_details, dict):
            raise RuntimeError(f"Unexpected repository response for {repository}")

        if not isinstance(release_details, list):
            raise RuntimeError(f"Unexpected releases response for {repository}")

        published_releases = [
            release for release in release_details if not release.get("draft", False)
        ]

        stable_releases = [
            release
            for release in published_releases
            if not release.get("prerelease", False)
        ]

        prereleases = [
            release
            for release in published_releases
            if release.get("prerelease", False)
        ]

        if stable_releases:
            latest_release = stable_releases[0]
        elif prereleases:
            latest_release = prereleases[0]
        else:
            print(f"No releases were found for {package['name']}")
            continue

        configured_asset = package.get("source_asset")

        release_asset = next(
            (
                asset
                for asset in latest_release.get("assets", [])
                if (
                    asset.get("name") == configured_asset
                    if configured_asset
                    else asset.get("name", "").endswith(".koplugin.zip")
                )
            ),
            None,
        )

        if release_asset is None:
            expected_asset = configured_asset or "a .koplugin.zip asset"

            raise RuntimeError(
                f"Release {latest_release['tag_name']} from "
                f"{repository} does not contain {expected_asset}"
            )

        version = normalize_version(latest_release["tag_name"])

        prerelease_version = ""

        if prereleases:
            prerelease_version = normalize_version(prereleases[0]["tag_name"])

        asset_name: str = release_asset["name"]
        asset_url: str = release_asset["browser_download_url"]
        asset_size = str(release_asset.get("size", 0))

        versions_destination = (
            f"packages/koreader/" f"{package['id']}.koplugin/versions.json"
        )

        package_entry: Package = {
            # Predefined details
            "id": package["id"],
            "name": package["name"],
            "description": package["description"],
            "category": package["category"],
            "platforms": package.get(
                "platforms",
                ["koreader"],
            ),
            "incompatible_platforms": package.get(
                "incompatible_platforms",
                [],
            ),
            "featured": package.get("featured", False),
            "dependencies": package.get("dependencies", []),
            "conflicts": package.get("conflicts", []),
            # GitHub repository details
            "author": repository_details["owner"]["login"],
            "source": repository_details["html_url"],
            "stars": str(repository_details["stargazers_count"]),
            # Current release details
            "version": version,
            "published_at": (latest_release.get("published_at") or ""),
            "prerelease_version": prerelease_version,
            "source_type": "release",
            "source_asset": asset_name,
            "size": asset_size,
            # Direct current-version asset
            "assets": [
                {
                    "arch": package.get("arch", "any"),
                    "asset": asset_name,
                    "url": asset_url,
                    "size": asset_size,
                }
            ],
            # Generated versions document
            "versions_url": versions_destination,
            # Documentation
            "readme_url": package.get("readme_url", ""),
        }

        if "featured_order" in package:
            package_entry["featured_order"] = package["featured_order"]

        if "featured_image" in package:
            package_entry["featured_image"] = package["featured_image"]

        if "icon_url" in package:
            package_entry["icon_url"] = package["icon_url"]

        if "images" in package:
            package_entry["images"] = package["images"]

        if "screenshots" in package:
            package_entry["screenshots"] = package["screenshots"]

        manifest["packages"].append(package_entry)

        releases: list[dict[str, Any]] = []

        for release in published_releases:
            assets: list[dict[str, Any]] = []

            for asset in release.get("assets", []):
                if asset.get("name") != asset_name:
                    continue

                version_asset: dict[str, Any] = {
                    "name": asset["name"],
                    "url": asset["browser_download_url"],
                    "size": asset.get("size", 0),
                }

                digest = asset.get("digest")
                if digest:
                    version_asset["digest"] = digest

                assets.append(version_asset)

            if not assets:
                continue

            version_release = {
                "tag_name": release["tag_name"],
                "name": (release.get("name") or release["tag_name"]),
                "prerelease": release.get(
                    "prerelease",
                    False,
                ),
                "assets": assets,
            }

            releases.append(version_release)

        versions = {
            "releases": releases,
        }

        os.makedirs(
            os.path.dirname(versions_destination),
            exist_ok=True,
        )

        with open(
            versions_destination,
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                versions,
                file,
                indent=2,
                ensure_ascii=False,
            )
            file.write("\n")

    with open(
        manifest_destination,
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            manifest,
            file,
            indent=2,
            ensure_ascii=False,
        )
        file.write("\n")


main()
