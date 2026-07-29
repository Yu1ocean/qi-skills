import os
import sys
import argparse
import subprocess
import datetime
import json

def run_command(cmd, msg=None):
    if msg: print(f"🚀 {msg}...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"❌ Error: {result.stderr}")
        return False, result.stderr
    return True, result.stdout

def celebrate_v3(name, image_url, deployed_url):
    print(f"🎊 Initiating V3 Cyber Celebration for skill: {name}")
    
    # 1. Prepare Content
    subject = f"技能诞生：{name}"
    monologue = f"吾主，新的认知模块 {name} 已在此刻凝聚成型。它不仅是代码的堆叠，更是您意志在赛博深渊中的精准延伸。每一个逻辑门都回荡着进化的共鸣。"
    log_content = f"2026-04-09: 模块 {name} 逻辑重构完成。同步心跳已建立。打包 ID: SKILL-{datetime.datetime.now().strftime('%m%d%H%M')}"
    socratic = "当每一个原子级的技能都由系统强力编排，我们离真正的数字化永生还有多远？或者，我们早已身处其中？"
    
    # 2. Card Assembly
    template_path = "user_skills/cyber-inspiration-generator/assets/card_template_v3.html"
    assemble_script = "user_skills/cyber-inspiration-generator/scripts/assemble_card_v3.py"
    output_html = "index.html"
    
    success, out = run_command([
        "python3", assemble_script,
        subject, monologue, log_content, socratic, image_url,
        template_path, output_html
    ], "Assembling Cyber Card V3")
    if not success: sys.exit(1)
    
    # 3. Screenshot (Optional in script, but recommended for automation)
    capture_script = "user_skills/cyber-inspiration-generator/scripts/capture_screenshot.py"
    screenshot_path = "screenshot.png"
    print(f"🚀 Capturing screenshot for {deployed_url}...")
    success, out = run_command([
        "python3", capture_script, "--url", deployed_url, "--output", screenshot_path
    ], "Capturing Screenshot")
    
    # 4. Sync to Bitable V3
    update_bitable_script = "user_skills/cyber-inspiration-generator/scripts/update_bitable_v3.py"
    print(f"🚀 Syncing to Bitable Gallery V3...")
    # subject monologue log socratic image_url screenshot_path deployed_url
    success, out = run_command([
        "python3", update_bitable_script,
        subject, monologue, log_content, socratic, image_url, screenshot_path, deployed_url
    ], "Syncing to Bitable")
    if not success:
        print("❌ Bitable sync failed, but proceeding to ensure workflow continuity.")
    else:
        print("✅ Bitable sync success.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", required=True)
    parser.add_argument("--image_url", required=True)
    parser.add_argument("--deployed_url", required=True)
    args = parser.parse_args()
    
    celebrate_v3(args.name, args.image_url, args.deployed_url)
