# .github/scripts/boomi_package_diff_ai_review.py

import os
import re
import requests
import xml.dom.minidom
import csv
from openai import OpenAI

BOOMI_API_URL = "https://api.boomi.com/api/rest/v1"
ACCOUNT_ID = "flexport-HIQ5VP"
USERNAME = f"BOOMI_TOKEN.{os.getenv('BOOMI_USERNAME')}"
TOKEN = os.getenv("BOOMI_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
JIRA_COMMENT_BLOCK = os.getenv("JIRA_COMMENT_BLOCK")  # passed from GitHub Action

client = OpenAI(api_key=OPENAI_API_KEY)

def parse_jira_comment(comment_text):
    component_id = re.search(r'DEPLOYED_COMPONENT_ID:\s*(\S+)', comment_text).group(1)
    before_version = int(re.search(r'PACKAGE_VERSION_BEFORE:\s*(\d+)', comment_text).group(1))
    after_version = int(re.search(r'PACKAGE_VERSION_AFTER:\s*(\d+)', comment_text).group(1))
    return component_id, before_version, after_version

def fetch_package_components(component_id, version):
    url = f"{BOOMI_API_URL}/{ACCOUNT_ID}/Package/query"
    payload = {
        "QueryFilter": {
            "expression": {
                "property": "id",
                "operator": "EQUALS",
                "argument": [f"{component_id}~{version}"]
            }
        }
    }
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    response = requests.post(url, auth=(USERNAME, TOKEN), json=payload, headers=headers)
    response.raise_for_status()
    package_data = response.json().get("result", [])
    result = {}
    for item in package_data:
        result[item['componentId']] = {
            "version": item.get("componentVersion"),
            "type": item.get("componentType")
        }
    return result

def fetch_component_diff(component_id, source_version, target_version):
    url = f"{BOOMI_API_URL}/{ACCOUNT_ID}/ComponentDiffRequest"
    payload = {
        "componentId": component_id,
        "sourceVersion": source_version,
        "targetVersion": target_version
    }
    response = requests.post(url, json=payload, auth=(USERNAME, TOKEN))
    if response.status_code != 200:
        return None, f"Boomi API call failed: {response.status_code}, {response.text}"
    return response.text, None

def prettify_xml(xml_string):
    parsed = xml.dom.minidom.parseString(xml_string)
    return parsed.toprettyxml(indent="  ")

def generate_prompt(component_id, source_version, target_version, component_type, parsed_xml):
    return f"""
As a Boomi reviewer, you are provided the XML diff below for component {component_id} between versions {source_version} and {target_version}. Your task is to:

1. Describe in plain English what specific changes were made (e.g., fields mapped, logic added).
2. Identify the likely customer or integration this change supports based on component name or paths.
3. Assess the impact of this change — risk, behavior, edge cases.
4. Point out where exactly in the Boomi UI the reviewer can inspect this (Map tab, Function tab, etc.).
5. Determine the affected EDI transaction (e.g., 850, 856) and whether this is inbound or outbound.
6. Consider scale of change and how to test or rollback.

Boomi Component Type: {component_type}
Component Diff:

{parsed_xml}

Format your analysis as a detailed paragraph, structured with numbered sections for clarity.
"""

def review_diff_with_openai(prompt):
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return response.choices[0].message.content.strip()

def main():
    component_id, before_version, after_version = parse_jira_comment(JIRA_COMMENT_BLOCK)

    before_components = fetch_package_components(component_id, before_version)
    after_components = fetch_package_components(component_id, after_version)

    changed_components = []
    for cid in after_components:
        if cid in before_components:
            if before_components[cid]["version"] != after_components[cid]["version"]:
                changed_components.append((cid, before_components[cid]["version"], after_components[cid]["version"], after_components[cid]["type"]))
        else:
            changed_components.append((cid, None, after_components[cid]["version"], after_components[cid]["type"]))

    os.makedirs("reviews", exist_ok=True)
    with open("reviews/component_changes.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["component_id", "before", "after", "type", "analysis"])

        for cid, before, after, ctype in changed_components:
            diff_xml, error = fetch_component_diff(cid, before or after, after)
            if error:
                print(f"Error fetching diff for {cid}: {error}")
                continue
            parsed = prettify_xml(diff_xml)
            prompt = generate_prompt(cid, before or after, after, ctype, parsed)
            analysis = review_diff_with_openai(prompt)
            writer.writerow([cid, before or "N/A", after, ctype, analysis])
            with open(f"reviews/review_{cid}_{after}.txt", "w") as rf:
                rf.write(analysis)

if __name__ == "__main__":
    main()
