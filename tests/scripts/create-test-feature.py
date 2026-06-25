#!/usr/bin/env python3
"""Create a test Feature ticket in Jira for workflow testing."""

import asyncio

from forge.integrations.jira.client import JiraClient


async def main():
    """Create the test feature ticket."""
    jira = JiraClient()

    try:
        client = await jira._get_client()

        # Build ADF description
        description = (
            "As of now in openshift-installer on openstack the bootstrap "
            "machine inherits its flavor from the control plane flavor shared "
            "with the masters. I would like to have a separate option that "
            "would allow configuring the flavor for the bootstrap machine."
        )
        adf_content = jira._text_to_adf(description)

        # Create the Feature ticket
        fields = {
            "project": {"key": "AISOS"},
            "summary": "Openshift installer add bootstrap machine flavor config",
            "description": adf_content,
            "issuetype": {"name": "Feature"},
            "labels": ["forge:managed"],
        }

        response = await client.post("/issue", json={"fields": fields})
        response.raise_for_status()

        data = response.json()
        issue_key = data["key"]
        issue_id = data["id"]

        print(f"Created Feature: {issue_key}")
        print(f"ID: {issue_id}")
        print(f"URL: {jira.settings.jira_base_url}/browse/{issue_key}")

    finally:
        await jira.close()


if __name__ == "__main__":
    asyncio.run(main())
