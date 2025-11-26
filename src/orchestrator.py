import json
import re
from .agent_b import AgentB
from .playwright_executor import PlaywrightExecutor


class Orchestrator:
    def __init__(self, screenshot_dir='./screenshots'):
        self.agent_b = AgentB()
        self.executor = PlaywrightExecutor(screenshot_dir)
        self.screenshot_dir = screenshot_dir

    async def initialize(self):
        await self.executor.initialize()

    async def cleanup(self):
        await self.executor.cleanup()

    async def process_task(self, task, app_url=None, credentials=None):
        if credentials is None:
            credentials = {}
        
        print(f"\n{'=' * 60}")
        print(f"Processing task: {task}")
        print(f"{'=' * 60}\n")

        try:
            # Step 1: Generate navigation plan using Agent B
            print('Agent B: Generating navigation plan...')
            import asyncio
            loop = asyncio.get_event_loop()
            navigation_plan = await loop.run_in_executor(
                None, 
                self.agent_b.generate_navigation_plan, 
                task, 
                app_url
            )
            
            # Extract app_url from plan if not provided
            if not app_url and 'app_url' in navigation_plan:
                app_url = navigation_plan['app_url']
                print(f'Detected application URL: {app_url}\n')
            
            print('\nGenerated Navigation Plan:')
            print(json.dumps(navigation_plan, indent=2))
            print('\n')

            # Step 2: Execute plan using Playwright
            print('Playwright: Executing navigation plan...')
            result = await self.executor.execute_plan(
                navigation_plan,
                self.sanitize_task_name(task),
                credentials
            )

            return result
        except Exception as error:
            print(f'Error processing task: {error}')
            raise

    def sanitize_task_name(self, task):
        return re.sub(r'[^a-z0-9]', '_', task.lower())[:50]

