"""Contract tests for ``qa_axe`` (QA Agent contract sections 7 and 9).

Axe results normalize to the shared finding dict: one finding per
``violations[].nodes[]``, impact mapped to severity, nested iframe targets
flattened, and ``incomplete[]`` reported as manual items -- never as a pass and
never as a failure.
"""

import copy
import json
import os
import pathlib
import sys
import unittest

_SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

try:  # pragma: no cover - package import
    from .. import qa_common as common
    from .. import qa_axe
except ImportError:  # pragma: no cover - direct script execution
    import qa_common as common
    import qa_axe


def _payload():
    """A representative axe-core result document."""
    return {
        "testEngine": {"name": "axe-core", "version": "4.10.0"},
        "url": "http://localhost:5173/checkout",
        "timestamp": "2026-07-25T14:04:11.000Z",
        "violations": [
            {
                "id": "color-contrast",
                "impact": "serious",
                "description": "Ensures the contrast between foreground and background colours",
                "help": "Elements must meet minimum colour contrast ratio thresholds",
                "helpUrl": "https://dequeuniversity.com/rules/axe/4.10/color-contrast",
                "tags": ["cat.color", "wcag2aa", "wcag143"],
                "nodes": [
                    {
                        "impact": "serious",
                        "target": [".hero .btn"],
                        "html": '<button class="btn">Buy</button>',
                        "failureSummary": "Fix any of the following: contrast is 2.9:1",
                    },
                    {
                        "impact": "critical",
                        "target": [["#payment-frame", "#inner"], ".pay-link"],
                        "html": '<a class="pay-link">Pay</a>',
                        "failureSummary": "Fix any of the following: contrast is 1.8:1",
                    },
                    {
                        "target": [".footer small"],
                        "html": "<small>terms</small>",
                        "failureSummary": "Fix any of the following: contrast is 3.1:1",
                    },
                ],
            },
            {
                "id": "image-alt",
                "impact": "critical",
                "help": "Images must have alternate text",
                "helpUrl": "https://dequeuniversity.com/rules/axe/4.10/image-alt",
                "tags": ["cat.text-alternatives", "wcag2a", "wcag111"],
                "nodes": [
                    {
                        "impact": "critical",
                        "target": ["img.logo"],
                        "html": '<img class="logo">',
                        "failureSummary": "Fix any of the following: element has no alt text",
                    }
                ],
            },
        ],
        "incomplete": [
            {
                "id": "aria-hidden-focus",
                "impact": "serious",
                "help": "aria-hidden elements must not be focusable",
                "helpUrl": "https://dequeuniversity.com/rules/axe/4.10/aria-hidden-focus",
                "nodes": [
                    {
                        "target": ["#tooltip"],
                        "html": '<div id="tooltip" aria-hidden="true">',
                        "failureSummary": "needs review",
                    }
                ],
            }
        ],
        "passes": [{"id": "region", "nodes": []}],
        "inapplicable": [{"id": "video-caption"}],
    }


class ImpactMappingTest(unittest.TestCase):
    """Section 4 / 7: the axe impact -> QA severity mapping."""

    def test_full_mapping(self):
        self.assertEqual(qa_axe.impact_to_severity("critical"), "critical")
        self.assertEqual(qa_axe.impact_to_severity("serious"), "high")
        self.assertEqual(qa_axe.impact_to_severity("moderate"), "medium")
        self.assertEqual(qa_axe.impact_to_severity("minor"), "low")

    def test_unknown_and_missing_impact_still_yield_a_contract_severity(self):
        for impact in (None, "", "unknown", "SERIOUS"):
            with self.subTest(impact=impact):
                self.assertIn(qa_axe.impact_to_severity(impact), common.SEVERITIES)

    def test_mapping_is_case_insensitive(self):
        self.assertEqual(qa_axe.impact_to_severity("Serious"), "high")


class NormalizeTest(unittest.TestCase):
    """Section 7: violations[].nodes[] fan out to one finding each."""

    def setUp(self):
        self.findings = qa_axe.normalize_axe_results(
            _payload(), route="/checkout", component="frontend/src/pages/checkout.tsx"
        )

    def test_one_finding_per_node(self):
        self.assertEqual(len(self.findings), 4)

    def test_findings_keep_the_input_order(self):
        self.assertEqual(
            [finding["rule"] for finding in self.findings],
            ["color-contrast", "color-contrast", "color-contrast", "image-alt"],
        )

    def test_rule_comes_from_the_violation_id(self):
        for finding in self.findings:
            self.assertIn(finding["rule"], ("color-contrast", "image-alt"))

    def test_source_is_a11y_and_line_is_zero(self):
        for finding in self.findings:
            with self.subTest(target=finding.get("target")):
                self.assertEqual(finding["source"], "a11y")
                self.assertEqual(finding["line"], 0)
                self.assertIsInstance(finding["line"], int)

    def test_node_impact_overrides_the_violation_impact(self):
        self.assertEqual(self.findings[0]["impact"], "serious")
        self.assertEqual(self.findings[1]["impact"], "critical")

    def test_node_without_impact_inherits_the_violation_impact(self):
        self.assertEqual(self.findings[2]["impact"], "serious")

    def test_target_selectors_are_joined_with_a_space(self):
        self.assertEqual(self.findings[0]["target"], ".hero .btn")
        self.assertEqual(self.findings[3]["target"], "img.logo")

    def test_nested_iframe_targets_are_flattened(self):
        self.assertEqual(self.findings[1]["target"], "#payment-frame #inner .pay-link")

    def test_help_url_is_carried_into_the_finding(self):
        self.assertEqual(
            self.findings[0]["helpUrl"],
            "https://dequeuniversity.com/rules/axe/4.10/color-contrast",
        )
        self.assertEqual(
            self.findings[3]["helpUrl"],
            "https://dequeuniversity.com/rules/axe/4.10/image-alt",
        )

    def test_component_wins_over_the_route_for_the_file(self):
        for finding in self.findings:
            self.assertEqual(finding["file"], "frontend/src/pages/checkout.tsx")

    def test_findings_carry_the_interchange_keys(self):
        for finding in self.findings:
            with self.subTest(target=finding.get("target")):
                for key in (
                    "source",
                    "rule",
                    "testId",
                    "name",
                    "file",
                    "line",
                    "target",
                    "impact",
                    "message",
                    "requirementRef",
                    "statedCriterion",
                    "flaky",
                    "helpUrl",
                ):
                    self.assertIn(key, finding)
                self.assertTrue(finding["name"])
                self.assertTrue(finding["message"])
                self.assertFalse(finding["flaky"])

    def test_severity_of_each_finding_follows_the_impact_mapping(self):
        self.assertEqual(qa_axe.impact_to_severity(self.findings[1]["impact"]), "critical")
        self.assertEqual(qa_axe.impact_to_severity(self.findings[0]["impact"]), "high")

    def test_incomplete_entries_are_not_findings(self):
        rules = set(finding["rule"] for finding in self.findings)
        self.assertNotIn("aria-hidden-focus", rules)

    def test_passes_are_not_findings(self):
        rules = set(finding["rule"] for finding in self.findings)
        self.assertNotIn("region", rules)
        self.assertNotIn("video-caption", rules)

    def test_normalization_is_deterministic(self):
        again = qa_axe.normalize_axe_results(
            _payload(), route="/checkout", component="frontend/src/pages/checkout.tsx"
        )
        self.assertEqual(json.dumps(again, sort_keys=True), json.dumps(self.findings, sort_keys=True))

    def test_normalization_does_not_mutate_the_payload(self):
        payload = _payload()
        snapshot = copy.deepcopy(payload)
        qa_axe.normalize_axe_results(payload, route="/checkout")
        self.assertEqual(payload, snapshot)


class RouteFallbackTest(unittest.TestCase):
    """Section 7: file falls back to the route URL when no component is known."""

    def test_route_is_used_when_no_component_is_given(self):
        findings = qa_axe.normalize_axe_results(_payload(), route="/checkout")
        self.assertTrue(findings)
        for finding in findings:
            self.assertEqual(finding["file"], "/checkout")

    def test_neither_route_nor_component_still_produces_a_string_file(self):
        findings = qa_axe.normalize_axe_results(_payload())
        self.assertTrue(findings)
        for finding in findings:
            self.assertIsInstance(finding["file"], str)


class IncompleteTest(unittest.TestCase):
    """Section 7: incomplete[] becomes a manual item, never a pass and never a failure."""

    def test_incomplete_entries_are_collected(self):
        items = qa_axe.collect_incomplete(_payload())
        self.assertEqual(len(items), 1)
        self.assertIsInstance(items[0], dict)
        self.assertIn("aria-hidden-focus", json.dumps(items))

    def test_manual_items_carry_a_reason(self):
        items = qa_axe.collect_incomplete(_payload())
        serialized = json.dumps(items[0]).lower()
        self.assertIn("reason", serialized)

    def test_a_payload_without_incomplete_yields_no_manual_items(self):
        payload = _payload()
        payload.pop("incomplete")
        self.assertEqual(qa_axe.collect_incomplete(payload), [])

    def test_empty_payload_yields_no_manual_items(self):
        self.assertEqual(qa_axe.collect_incomplete({}), [])


class RoutePathTest(unittest.TestCase):
    """`file` feeds the fingerprint, so it must not bind a page to a host:port."""

    def test_absolute_urls_reduce_to_their_path(self):
        for url, expected in (
            ("http://localhost:5173/dashboard", "/dashboard"),
            ("http://127.0.0.1:4173/dashboard", "/dashboard"),
            ("https://staging.example.invalid/cart?step=2#top", "/cart"),
            ("http://localhost:5173", "/"),
        ):
            with self.subTest(url=url):
                self.assertEqual(qa_axe.route_path(url), expected)

    def test_non_urls_are_left_alone(self):
        for value in ("frontend/src/components/user-menu.tsx", "/dashboard", ""):
            with self.subTest(value=value):
                self.assertEqual(qa_axe.route_path(value), value)

    def test_the_same_page_fingerprints_identically_across_hosts(self):
        payload = {
            "violations": [
                {
                    "id": "meta-viewport",
                    "impact": "critical",
                    "nodes": [{"target": ['meta[name="viewport"]'], "impact": "critical"}],
                }
            ]
        }
        dev = qa_axe.normalize_axe_results(payload, route="http://localhost:5173/dashboard")
        ci = qa_axe.normalize_axe_results(payload, route="http://127.0.0.1:4173/dashboard")
        self.assertEqual(dev[0]["file"], ci[0]["file"])
        self.assertEqual(dev[0]["file"], "/dashboard")


class ToleranceTest(unittest.TestCase):
    """Section 7: the @axe-core/playwright subset payload must not break parsing."""

    def test_minimal_violations_only_payload(self):
        payload = {
            "violations": [
                {"id": "label", "nodes": [{"target": ["#email"]}]},
            ]
        }
        findings = qa_axe.normalize_axe_results(payload, route="/signup")
        self.assertEqual(len(findings), 1)
        finding = findings[0]
        self.assertEqual(finding["rule"], "label")
        self.assertEqual(finding["target"], "#email")
        self.assertIsNone(finding["helpUrl"])
        self.assertEqual(finding["source"], "a11y")
        self.assertIn(qa_axe.impact_to_severity(finding["impact"]), common.SEVERITIES)

    def test_empty_payload_yields_no_findings(self):
        self.assertEqual(qa_axe.normalize_axe_results({}), [])

    def test_violation_without_nodes_yields_no_findings(self):
        payload = {"violations": [{"id": "region", "impact": "moderate", "nodes": []}]}
        self.assertEqual(qa_axe.normalize_axe_results(payload), [])

    def test_missing_violations_key_yields_no_findings(self):
        self.assertEqual(qa_axe.normalize_axe_results({"passes": [], "incomplete": []}), [])

    def test_empty_violations_list_yields_no_findings(self):
        payload = {"violations": []}
        self.assertEqual(qa_axe.normalize_axe_results(payload), [])
        self.assertEqual(qa_axe.collect_incomplete(payload), [])


class ModuleSurfaceTest(unittest.TestCase):
    """Section 9: qa_axe is a library module -- it owns no subcommand."""

    def test_exposes_the_library_functions(self):
        for name in ("normalize_axe_results", "impact_to_severity", "collect_incomplete"):
            with self.subTest(function=name):
                self.assertTrue(callable(getattr(qa_axe, name, None)))

    def test_declares_no_subcommand(self):
        self.assertIsNone(getattr(qa_axe, "COMMAND", None))
        self.assertIsNone(getattr(qa_axe, "COMMANDS", None))


if __name__ == "__main__":  # pragma: no cover - manual execution
    unittest.main()
