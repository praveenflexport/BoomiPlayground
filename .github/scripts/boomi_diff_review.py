import os
import csv
import requests
import xml.dom.minidom
from openai import OpenAI

BOOMI_API_URL = "https://api.boomi.com/api/rest/v1"
ACCOUNT_ID = "flexport-HIQ5VP"
USERNAME = f"BOOMI_TOKEN.{os.getenv('BOOMI_USERNAME')}"
TOKEN = os.getenv("BOOMI_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def prettify_xml(xml_string):
    parsed = xml.dom.minidom.parseString(xml_string)
    return parsed.toprettyxml(indent="  ")


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


def generate_prompt(component_id, source_version, target_version, component_type="Process", change_type="feature", parsed_xml=""):
    return (
        f"As a Boomi reviewer, you are provided the XML diff below for component {component_id} "
        f"between versions {source_version} and {target_version}. Your task is to:\n\n"
        "1. Describe in plain English what specific changes were made (e.g., fields mapped, logic added).\n"
        "2. Identify the likely customer or integration this change supports based on component name or paths.\n"
        "3. Assess the impact of this change — risk, behavior, edge cases.\n"
        "4. Point out where exactly in the Boomi UI the reviewer can inspect this (Map tab, Function tab, etc.).\n"
        "5. Determine the affected EDI transaction (e.g., 850, 856) and whether this is inbound or outbound.\n"
        "6. Consider scale of change and how to test or rollback.\n\n"
        f"Boomi Component Type: {component_type}\n"
        f"Change Type: {change_type}\n"
        "Component Diff:\n\n"
        f"{parsed_xml}\n\n"
        "Format your analysis as a detailed paragraph, structured with numbered sections for clarity."
    )


def review_diff_with_openai(prompt):
    client = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.3
    )
    return response.choices[0].message.content.strip()


with open("readyForCodeReview.csv", newline="") as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        component_id = row["componentid"]
        source_version = int(row["before"])
        target_version = int(row["after"])
        assignee = row["modifiedBy"]

        print(f"\n🔍 Processing Component: {component_id}, Versions: {source_version} -> {target_version}")

        diff_xml, error = fetch_component_diff(component_id, source_version, target_version)
        if error:
            print(f"❌ {error}")
            continue

        parsed_xml = prettify_xml(diff_xml)
        prompt = generate_prompt(component_id, source_version, target_version, parsed_xml=parsed_xml)
        analysis = review_diff_with_openai(prompt)

        filename = f"review_{component_id}_{target_version}.txt"
        with open(filename, "w") as f:
            f.write(f"Assignee: {assignee}\n\n")
            f.write(analysis)

        print(f"✅ Saved review to {filename}")
