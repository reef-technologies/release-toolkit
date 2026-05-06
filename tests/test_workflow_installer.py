from __future__ import annotations

from release_toolkit.workflow_installer import (
    RELEASE_WORKFLOW_USES_PREFIX,
    RELEASE_WORKFLOW_USES_REF,
    WorkflowConfig,
    is_release_workflow_caller,
    render_workflow,
)


class TestWorkflowConfigFactories:
    def test_for_single_uses_v_prefix_and_release_filename(self):
        assert WorkflowConfig.for_single() == WorkflowConfig(
            package_dir=".",
            tag_prefix="v",
            workflow_name="Release",
            file_name="release.yml",
        )

    def test_for_single_accepts_custom_package_dir(self):
        config = WorkflowConfig.for_single("subproject")
        assert config.package_dir == "subproject"
        assert config.tag_prefix == "v"

    def test_for_monorepo_uses_project_name_in_prefix_and_filename(self):
        assert WorkflowConfig.for_monorepo("client", "packages/client") == WorkflowConfig(
            package_dir="packages/client",
            tag_prefix="client-v",
            workflow_name="Release (client)",
            file_name="release-client.yml",
        )


class TestRenderWorkflow:
    def test_single_output_contains_expected_values(self):
        text = render_workflow(WorkflowConfig.for_single())

        assert "name: Release\n" in text
        assert "      - 'v*'\n" in text
        assert f"    uses: {RELEASE_WORKFLOW_USES_REF}\n" in text
        assert "      package_dir: .\n" in text
        assert "      tag_prefix: v\n" in text
        assert text.endswith("\n")

    def test_monorepo_output_contains_named_prefix_and_dir(self):
        text = render_workflow(WorkflowConfig.for_monorepo("client", "packages/client"))

        assert "name: Release (client)\n" in text
        assert "      - 'client-v*'\n" in text
        assert "      package_dir: packages/client\n" in text
        assert "      tag_prefix: client-v\n" in text

    def test_secrets_block_uses_double_dollar_brace_for_actions_template(self):
        text = render_workflow(WorkflowConfig.for_single())

        assert "SLACK_WEBHOOK_URL: ${{ secrets.SLACK_WEBHOOK_URL }}" in text

    def test_rendered_workflow_has_no_inline_disable_slack_comment(self):
        text = render_workflow(WorkflowConfig.for_single())

        assert "omit this line" not in text
        assert "disable Slack" not in text


class TestIsReleaseWorkflowCaller:
    def test_detects_v1_pin(self):
        text = "jobs:\n  release:\n    uses: " + RELEASE_WORKFLOW_USES_PREFIX + "v1\n"
        assert is_release_workflow_caller(text) is True

    def test_detects_sha_pin(self):
        text = "uses: " + RELEASE_WORKFLOW_USES_PREFIX + "abc1234\n"
        assert is_release_workflow_caller(text) is True

    def test_returns_false_for_unrelated_workflow(self):
        text = "jobs:\n  build:\n    uses: actions/checkout@v4\n"
        assert is_release_workflow_caller(text) is False

    def test_returns_false_for_empty_text(self):
        assert is_release_workflow_caller("") is False

    def test_rendered_workflow_is_self_detected(self):
        text = render_workflow(WorkflowConfig.for_single())
        assert is_release_workflow_caller(text) is True
