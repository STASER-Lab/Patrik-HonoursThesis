"""Bot detection for GitHub accounts, applied to every author in the ETL."""

from __future__ import annotations

CURATED_BOT_LOGINS: frozenset[str] = frozenset(
    {
        # Dependencies
        "dependabot",
        "dependabot-preview",
        "renovate",
        "renovate-bot",
        "pyup-bot",
        "greenkeeper",
        "r-ryantm",
        # CI, build and test
        "travis",
        "travis-ci",
        "circleci",
        "appveyor",
        "azure-pipelines",
        "buildkite-bot",
        "drone-io",
        "jenkins-bot",
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
        "snyk-bot",
        "whitesource-bolt-for-github",
        "deepsource-autofix",
        "github-advanced-security",
        "mateacademy-ai-mentor",
        # Release
        "semantic-release-bot",
        "release-drafter",
        "changeset-bot",
        "github-actions",
        "aws-cdk-automation",
        "juliaregistrator",
        "modular-magician",
        "osbotify",
        # Documentation, maintenance
        "allcontributors",
        "all-contributors",
        "backportbot",
        "bors",
        "homu",
        "probot",
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
        "everypoliticianbot",
        "depfu",
        "scala-steward",
        "imgbot",
        "docker-library-bot",
        "siteleaf",
        "yoshi-automation",
        "yoshi-code-bot",
    }
)

CURATED_BOT_PREFIXES: tuple[str, ...] = (
    "aws-aemilia-",
    "amplify-github-test-",
)

KNOWN_HUMAN_LOGINS: frozenset[str] = frozenset(
    {
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
)
KNOWN_HUMAN_SUFFIXES: tuple[str, ...] = ("talbot",)


def is_bot_account(user: dict) -> bool:
    login = str(user.get("login") or "").strip().casefold()
    account_type = str(user.get("type") or "").strip().casefold()
    if (
        account_type == "bot"
        or login.endswith("[bot]")
        or login in CURATED_BOT_LOGINS
        or login.startswith(CURATED_BOT_PREFIXES)
    ):
        return True
    if login in KNOWN_HUMAN_LOGINS or login.endswith(KNOWN_HUMAN_SUFFIXES):
        return False
    return login.endswith("bot")
