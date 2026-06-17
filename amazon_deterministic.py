import asyncio
import sys
import os

# Ensure the git repo root is in Python path
workspace_path = "/Users/swapniel/git/dag_architecture"
if workspace_path not in sys.path:
    sys.path.insert(0, workspace_path)

from schemas import NodeSpec
from browser.skill import BrowserSkill

async def main():
    skill = BrowserSkill()

    # Define selectors for amazon.in search
    node = NodeSpec(
        skill="browser",
        metadata={
            "url": "https://www.amazon.in/",
            "goal": "Search laptops, filter by HP, and click first product",
            "selectors": [
                # 1. Fill search box
                {
                    "action": "fill",
                    "selector": "#twotabsearchtextbox",
                    "value": "laptops"
                },
                # 2. Click Search button
                {
                    "action": "click",
                    "selector": "#nav-search-submit-button"
                },
                # 3. Fill low price boundary
                {
                    "action": "fill",
                    "selector": "#low-price",
                    "value": "50000"
                },
                # 4. Fill high price boundary
                {
                    "action": "fill",
                    "selector": "#high-price",
                    "value": "80000"
                },
                # 5. Click Go button for price filter
                {
                    "action": "click",
                    "selector": "form:has(#low-price) input[type='submit']"
                },
                # 6. Click HP brand filter link
                {
                    "action": "click",
                    "selector": "a.s-navigation-item:has(span:text-is('HP'))"
                },
                # 7. Click the first product title link (robust across grid/list layout)
                {
                    "action": "click",
                    "selector": "[data-cy='title-recipe'] a"
                }
            ]
        }
    )

    print("Running Amazon.in complex flow with correct selectors...")
    result = await skill.run(node)

    print("\nResult Success:", result.success)
    print("Result Path Used:", result.output.get("path"))
    print("Result Final URL:", result.output.get("final_url"))
    print("Result Error (if any):", result.error)
    print("Result Content (Truncated):", result.output.get("content")[:500] if result.output.get("content") else None)

if __name__ == "__main__":
    asyncio.run(main())
