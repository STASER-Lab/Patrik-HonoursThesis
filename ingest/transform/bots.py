"""Bot detection for GitHub accounts.

The lists are frozen: changing them changes every tier's records.
"""

from __future__ import annotations

# Bots the `bot` suffix rule in is_bot_account misses
CURATED_BOT_LOGINS = {
    # Dependencies
    "dependabot-preview",
    "renovate",
    "greenkeeper",
    "r-ryantm",
    # CI, build and test
    "travis",
    "travis-ci",
    "circleci",
    "appveyor",
    "azure-pipelines",
    "drone-io",
    "ci-tester-lunarg",
    "cmsbuild",
    "cockroach-teamcity",
    "elasticmachine",
    "elasticsearchmachine",
    "guru-dev-cicd-canary-beta",
    "hmcts-platform-operations",
    "istio-testing",
    "kibanamachine",
    "liferay-continuous-integration",
    "mssonicbld",
    "syncfusionbuild",
    "team-tf-cdk",
    "terraform-ibm-modules-ops",
    "vs-mobiletools-engineering-service2",
    "webkit-early-warning-system",
    # Test accounts
    "plutointegtestuser",
    "qlikqaa",
    "signcla-test-signed-corp",
    "signcla-test-signed-indiv",
    "signcla-test-unsigned",
    "terrateam-test-user01",
    # Code
    "codecov",
    "codecov-io",
    "codecov-commenter",
    "coveralls",
    "sonarcloud",
    "whitesource-bolt-for-github",
    "deepsource-autofix",
    "github-advanced-security",
    "mateacademy-ai-mentor",
    # Release
    "release-drafter",
    "github-actions",
    "aws-cdk-automation",
    "juliaregistrator",
    "modular-magician",
    "osbotify",
    # Documentation and maintenance
    "allcontributors",
    "all-contributors",
    "bors",
    "homu",
    "stale",
    "mergify",
    "kodiakhq",
    "azure-sdk",
    "claassistant",
    "conda-forge-admin",
    "robodoo",
    "truecharts-admin",
    "weblate",
    # Other
    "depfu",
    "scala-steward",
    "siteleaf",
    "yoshi-automation",
}

CURATED_BOT_PREFIXES = (
    "aws-aemilia-",
    "amplify-github-test-",
)

KNOWN_HUMAN_LOGINS = {
    "artfulrobot",
    "awesomerobot",
    "ceejbot",
    "grafikrobot",
    "jared-thoughtbot",
    "julien-lebot",
    "kishlay-notabot",
    "miquelcabot",
    "olgabot",
    "paleolimbot",
    "timidrobot",
}

KNOWN_HUMAN_SUFFIXES = ("talbot",)


def is_bot_account(user: dict) -> bool:
    login = (user.get("login") or "").strip().casefold()
    account_type = (user.get("type") or "").strip().casefold()
    if (
        account_type == "bot"
        or login in CURATED_BOT_LOGINS
        or login.startswith(CURATED_BOT_PREFIXES)
    ):
        return True
    if login in KNOWN_HUMAN_LOGINS or login.endswith(KNOWN_HUMAN_SUFFIXES):
        return False
    return login.endswith(("bot", "[bot]"))
