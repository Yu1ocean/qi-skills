#!/usr/bin/env python3
import os
import sys
import datetime
import uuid

def assemble_card(subject, story_content, fact_content, image_url, template_path, output_path):
    with open(template_path, 'r', encoding='utf-8') as f:
        template = f.read()
    
    date_str = datetime.date.today().strftime('%Y-%m-%d')
    unique_id = str(uuid.uuid4())[:8].upper()
    
    final_html = template.replace('{{ SUBJECT }}', subject)
    final_html = final_html.replace('{{ DATE }}', date_str)
    final_html = final_html.replace('{{ IMAGE_URL }}', image_url)
    final_html = final_html.replace('{{ STORY_CONTENT }}', story_content)
    final_html = final_html.replace('{{ FACT_CONTENT }}', fact_content)
    final_html = final_html.replace('{{ UID }}', unique_id)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(final_html)
    
    print(f"✅ Card assembled successfully at: {output_path}")

if __name__ == "__main__":
    if len(sys.argv) < 6:
        print("Usage: python3 assemble_card.py <subject> <story_content> <fact_content> <image_url> <template_path> <output_path>")
        sys.exit(1)
    
    subject = sys.argv[1]
    story_content = sys.argv[2]
    fact_content = sys.argv[3]
    image_url = sys.argv[4]
    template_path = sys.argv[5]
    output_path = sys.argv[6]
    
    assemble_card(subject, story_content, fact_content, image_url, template_path, output_path)
