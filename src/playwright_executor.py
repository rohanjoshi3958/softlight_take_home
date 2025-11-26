import os
import re
import time
from datetime import datetime
from pathlib import Path
from playwright.async_api import async_playwright, Browser, BrowserContext, Page
from .element_helpers import click_text_element, click_symbol_element
from .page_helpers import is_login_page, wait_for_manual_login, get_url_state, wait_for_url_change


class PlaywrightExecutor:
    def __init__(self, screenshot_dir='./screenshots'):
        self.screenshot_dir = screenshot_dir
        self.previous_failed_text_selector = None  # Track failed text selectors for context extraction
        self.browser: Browser = None
        self.page: Page = None
        self.context: BrowserContext = None
        self.playwright = None
        self.run_folder = None  # Will be set during initialize()

    async def initialize(self):
        self.playwright = await async_playwright().start()
        # Use Google Chrome (chromium) instead of Firefox
        self.browser = await self.playwright.chromium.launch(
            headless=False,  # Set to True for headless mode
            slow_mo=500,  # Slow down actions for visibility
            channel='chrome'  # Use Google Chrome instead of Chromium
        )
        self.context = await self.browser.new_context(
            viewport={'width': 1920, 'height': 1080}
        )
        self.page = await self.context.new_page()
        
        # Ensure base screenshot directory exists
        Path(self.screenshot_dir).mkdir(parents=True, exist_ok=True)
        
        # Create a unique folder for this run (timestamp-based)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]  # Include milliseconds
        self.run_folder = Path(self.screenshot_dir) / f"run_{timestamp}"
        self.run_folder.mkdir(parents=True, exist_ok=True)
        print(f"Screenshots will be saved to: {self.run_folder}")

    async def cleanup(self):
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()

    async def capture_screenshot(self, step_number, goal, task_name, action_suffix=""):
        # Use the run folder created during initialize()
        if self.run_folder is None:
            # Fallback: create a run folder if initialize() wasn't called
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
            self.run_folder = Path(self.screenshot_dir) / f"run_{timestamp}"
            self.run_folder.mkdir(parents=True, exist_ok=True)
        
        # Create a safe filename from goal and step number
        sanitized_goal = re.sub(r'[^a-z0-9]', '_', goal.lower())[:50]  # Limit length
        suffix = f"_{action_suffix}" if action_suffix else ""
        filename = f"step_{step_number:02d}_{sanitized_goal}{suffix}.png"
        filepath = self.run_folder / filename
        
        await self.page.screenshot(
            path=str(filepath),
            full_page=True
        )
        
        return str(filepath)
    
    async def _is_login_related_step(self, goal):
        """Check if the current step is login-related or if we're on a login page."""
        # Check if we're currently on a login page
        if await self.is_login_page():
            return True
        
        # Check if the goal is login-related
        if not goal:
            return False
        goal_lower = goal.lower()
        return any(keyword in goal_lower for keyword in ['login', 'log in', 'sign in', 'authenticate', 'credentials'])
    
    async def _capture_screenshot_after_action(self, step_number, goal, task_name, action_type):
        """Helper method to capture screenshot after a successful action (unless login-related)."""
        if not await self._is_login_related_step(goal):
            await self.page.wait_for_timeout(300)  # Small delay for UI to update
            screenshot_path = await self.capture_screenshot(
                step_number,
                goal,
                task_name,
                f"after_{action_type}"
            )
            print(f"  Screenshot captured after {action_type}: {screenshot_path}")
            return screenshot_path
        return None

    async def is_login_page(self):
        """Detect if we're on a login page by checking for common login indicators."""
        return await is_login_page(self.page)

    async def wait_for_manual_login(self, post_login_indicators=None):
        """Pause execution and wait for user to manually log in, then detect when login is complete."""
        # Capture screenshot of login page
        await self.capture_screenshot(0, "login_page", "manual_login")
        return await wait_for_manual_login(self.page, post_login_indicators)

    async def _click_text_element(self, text):
        """Helper method to click text elements with multiple fallback strategies."""
        return await click_text_element(self.page, text)
    
    async def _click_symbol_element(self, symbol, context_keywords=None):
        """Helper method to click symbol/icon elements (like +, ×, etc.)."""
        # Get URL state function for context inference
        async def get_url_state_func():
            return await self._get_url_state()
        return await click_symbol_element(self.page, symbol, context_keywords, get_url_state_func)

    async def execute_action(self, action, step_number, goal, task_name, credentials=None, used_input_fields=None):
        if credentials is None:
            credentials = {}
        if used_input_fields is None:
            used_input_fields = []
        
        print(f"  Executing: {action}")
        
        try:
            # Replace placeholders with actual values
            processed_action = action
            if credentials.get('email'):
                processed_action = processed_action.replace('<EMAIL>', credentials['email'])
            if credentials.get('password'):
                processed_action = processed_action.replace('<PASSWORD>', credentials['password'])
            if credentials.get('project_name'):
                processed_action = processed_action.replace('<PROJECT_NAME>', credentials['project_name'])
            if credentials.get('description'):
                processed_action = processed_action.replace('<DESCRIPTION>', credentials['description'])

            # Parse and execute different action types
            if processed_action.startswith('open_page('):
                match = re.search(r"open_page\('([^']+)'\)", processed_action)
                if match:
                    url = match.group(1)
                    try:
                        # Use 'load' instead of 'networkidle' - more reliable for SPAs
                        # 'networkidle' often times out on modern apps with continuous network activity
                        await self.page.goto(url, wait_until='load', timeout=60000)
                    except Exception as goto_error:
                        # If 'load' times out, try 'domcontentloaded' as fallback
                        print(f"  Warning: 'load' wait timed out, trying 'domcontentloaded'...")
                        try:
                            await self.page.goto(url, wait_until='domcontentloaded', timeout=30000)
                        except:
                            # If both fail, just navigate without waiting (page might still load)
                            print(f"  Warning: Navigation wait failed, but page may have loaded. Continuing...")
                            await self.page.goto(url, timeout=10000)
                    
                    # Wait a bit for any dynamic content to load
                    await self.page.wait_for_timeout(2000)
                    
                    # Check if we landed on a login page
                    if await self.is_login_page():
                        await self.wait_for_manual_login()
                        # Screenshot after login will be captured at end of step
                    else:
                        # Capture screenshot after page loads (unless login-related)
                        await self._capture_screenshot_after_action(step_number, goal, task_name, "open_page")
            
            elif processed_action.startswith('wait_for('):
                match = re.search(r"wait_for\('([^']+)'\)", processed_action)
                if match:
                    selector = match.group(1)
                    try:
                        # Handle text-based waits
                        if selector.startswith('text='):
                            text = selector.replace('text=', '')
                            # Try exact match first
                            try:
                                await self.page.wait_for_selector(f"text={text}", timeout=10000)
                            except:
                                # Try case-insensitive partial match
                                await self.page.wait_for_selector(f"text=/{text}/i", timeout=10000)
                        else:
                            # For input/textarea selectors, also check in modals/dialogs
                            if 'input' in selector.lower() or 'textarea' in selector.lower():
                                # Try the selector as-is first
                                try:
                                    await self.page.wait_for_selector(selector, timeout=5000)
                                except:
                                    # Try looking in modals/dialogs (try each separately)
                                    found = False
                                    for modal_selector in [
                                        f'[role="dialog"] {selector}',
                                        f'[role="modal"] {selector}',
                                        f'form {selector}',
                                        selector  # Fall back to original
                                    ]:
                                        try:
                                            await self.page.wait_for_selector(modal_selector, timeout=3000)
                                            found = True
                                            break
                                        except:
                                            continue
                                    if not found:
                                        # Last attempt with original selector
                                        await self.page.wait_for_selector(selector, timeout=10000)
                            else:
                                await self.page.wait_for_selector(selector, timeout=10000)
                    except Exception as e:
                        print(f"  Warning: Selector '{selector}' not found within timeout")
                        # Try fallback strategies for common patterns
                        fallback_success = False
                        if 'input' in selector.lower() or 'textarea' in selector.lower():
                            print(f"  Trying fallback: waiting for any text input or textarea (including in modals)...")
                            # Try modals/dialogs first, then anywhere
                            fallback_selectors = [
                                '[role="dialog"] textarea, [role="modal"] textarea',
                                '[role="dialog"] input[type="text"], [role="modal"] input[type="text"]',
                                'form textarea',
                                'form input[type="text"]',
                                'textarea',
                                'input[type="text"], input[type="search"]'
                            ]
                            for fallback_sel in fallback_selectors:
                                try:
                                    await self.page.wait_for_selector(fallback_sel, timeout=2000)
                                    print(f"  Found input/textarea, continuing...")
                                    fallback_success = True
                                    break
                                except:
                                    continue
                        if not fallback_success and 'form' in selector.lower():
                            print(f"  Trying fallback: waiting for any form...")
                            try:
                                await self.page.wait_for_selector('form', timeout=3000)
                                print(f"  Found form, continuing...")
                                fallback_success = True
                            except:
                                pass
                        if not fallback_success and 'button' in selector.lower():
                            print(f"  Trying fallback: waiting for any button...")
                            try:
                                await self.page.wait_for_selector('button', timeout=3000)
                                print(f"  Found button, continuing...")
                                fallback_success = True
                            except:
                                pass
                        if not fallback_success and selector.startswith('text='):
                            # For text waits, just wait a bit for dynamic content
                            text = selector.replace('text=', '')
                            print(f"  Text '{text}' not found, waiting for page to settle...")
                            await self.page.wait_for_timeout(2000)
                            fallback_success = True
                        
                        if not fallback_success:
                            # For any selector, check if page has any elements (generic page load check)
                            print(f"  Checking if page has loaded (looking for any elements)...")
                            try:
                                # Wait for any common elements to appear (body, main content, etc.)
                                await self.page.wait_for_selector('body', timeout=5000)
                                # Check if page has any interactive elements
                                element_count = await self.page.evaluate('() => document.querySelectorAll("*").length')
                                if element_count > 10:  # Page likely loaded if it has more than 10 elements
                                    print(f"  Page appears to be loaded ({element_count} elements found), continuing...")
                                else:
                                    print(f"  Page may still be loading, waiting a bit more...")
                                    await self.page.wait_for_timeout(2000)
                            except:
                                # If even body doesn't exist, just wait a bit
                                print(f"  Waiting for page to settle...")
                                await self.page.wait_for_timeout(2000)
                    # Capture screenshot after wait_for completes (unless login-related)
                    await self._capture_screenshot_after_action(step_number, goal, task_name, "wait_for")
            
            elif processed_action.startswith('wait_for_selector('):
                # Support alternative format: wait_for_selector('selector')
                match = re.search(r"wait_for_selector\('([^']+)'\)", processed_action)
                if match:
                    selector = match.group(1)
                    try:
                        await self.page.wait_for_selector(selector, timeout=10000)
                    except Exception as e:
                        print(f"  Warning: Selector '{selector}' not found within timeout")
                        # Try fallback - wait for page to be interactive
                        print(f"  Waiting for page to be ready...")
                        await self.page.wait_for_timeout(2000)
                    # Capture screenshot after wait_for_selector completes (unless login-related)
                    await self._capture_screenshot_after_action(step_number, goal, task_name, "wait_for_selector")
            
            elif processed_action.startswith('wait_for_page_ready(') or processed_action.startswith('wait_for_page_load('):
                # Generic wait for page to be ready
                print(f"  Waiting for page to be ready...")
                await self.page.wait_for_load_state('networkidle', timeout=10000)
                await self.page.wait_for_timeout(1000)  # Additional wait for dynamic content
                # Capture screenshot after page is ready (unless login-related)
                await self._capture_screenshot_after_action(step_number, goal, task_name, "wait_for_page_ready")
            
            elif processed_action.startswith('wait_for_either('):
                match = re.search(r"wait_for_either\('([^']+)',\s*'([^']+)'\)", processed_action)
                if match:
                    selector1 = match.group(1)
                    selector2 = match.group(2)
                    try:
                        await self.page.wait_for_selector(selector1, timeout=5000)
                    except:
                        await self.page.wait_for_selector(selector2, timeout=5000)
                    
                    # Check if selector2 is a login form - if so, wait for manual login
                    if 'login' in selector2.lower() or 'signin' in selector2.lower():
                        if await self.is_login_page():
                            await self.wait_for_manual_login()
                            # Screenshot after login will be captured at end of step
                        else:
                            # Capture screenshot after wait_for_either completes (unless login-related)
                            await self._capture_screenshot_after_action(step_number, goal, task_name, "wait_for_either")
                    else:
                        # Capture screenshot after wait_for_either completes (unless login-related)
                        await self._capture_screenshot_after_action(step_number, goal, task_name, "wait_for_either")
            
            elif processed_action.startswith('wait_for_url_change('):
                # Wait for URL to change (useful for validating navigation/actions)
                print(f"  Waiting for URL to change...")
                initial_url = self.page.url
                try:
                    # Wait for URL to change (with timeout)
                    await self.page.wait_for_function(
                        f"window.location.href !== '{initial_url}'",
                        timeout=10000
                    )
                    new_url = self.page.url
                    print(f"  URL changed: {initial_url[:50]}... → {new_url[:50]}...")
                    url_state = await self._get_url_state()
                    state_indicators = [k for k, v in url_state.items() if v and k not in ['url', 'path_parts', 'query_params']]
                    if state_indicators:
                        print(f"  URL state: {', '.join(state_indicators)}")
                    # Capture screenshot after URL change (unless login-related)
                    await self._capture_screenshot_after_action(step_number, goal, task_name, "wait_for_url_change")
                except:
                    print(f"  Warning: URL did not change within timeout")
                    # Fallback: wait for page to be ready
                    await self.page.wait_for_timeout(2000)
            
            elif processed_action.startswith('if_url_contains('):
                # Conditional check based on URL pattern (PRIMARY strategy for state validation)
                match = re.search(r"if_url_contains\('([^']+)',\s*proceed_to_step=(\d+)\)", processed_action)
                if match:
                    pattern = match.group(1)
                    target_step = int(match.group(2))
                    try:
                        current_url = self.page.url.lower()
                        if pattern.lower() in current_url:
                            url_state = await self._get_url_state()
                            print(f"  URL contains '{pattern}' - current URL: {self.page.url[:80]}...")
                            state_indicators = [k for k, v in url_state.items() if v and k not in ['url', 'path_parts', 'query_params']]
                            if state_indicators:
                                print(f"  URL state: {', '.join(state_indicators)}")
                            return {'skip': True, 'step': target_step}
                        else:
                            print(f"  URL does not contain '{pattern}' - current URL: {self.page.url[:80]}...")
                            # Fallback: try element-based check if URL check fails
                            return {'condition': True, 'result': False}
                    except Exception as e:
                        print(f"  Error checking URL: {e}")
                        # Fallback: try element-based check
                        return {'condition': True, 'result': False}
            
            elif processed_action.startswith('if_visible('):
                match = re.search(r"if_visible\('([^']+)'\)", processed_action)
                if match:
                    selector = match.group(1)
                    try:
                        is_visible = await self.page.locator(selector).is_visible()
                    except:
                        is_visible = False
                    
                    # If login form is visible, wait for manual login
                    if is_visible and ('login' in selector.lower() or 'signin' in selector.lower()):
                        if await self.is_login_page():
                            await self.wait_for_manual_login()
                            # Screenshot after login will be captured at end of step
                    
                    return {'condition': True, 'result': is_visible}
            
            elif processed_action.startswith('if_element_exists(') or processed_action.startswith('else if_element_exists('):
                # Support: if_element_exists('selector', proceed_to_step=N) or else if_element_exists('selector', proceed_to_step=N)
                match = re.search(r"if_element_exists\('([^']+)',\s*proceed_to_step=(\d+)\)", processed_action)
                if match:
                    selector = match.group(1)
                    target_step = int(match.group(2))
                    try:
                        if selector.startswith('text='):
                            text = selector.replace('text=', '')
                            # Try to find exact text match first (to avoid matching "My issues" when looking for "Issues")
                            exists = False
                            locator = None
                            try:
                                # Find all elements containing the text
                                all_elements = self.page.locator(f'text=/{text}/i')
                                count = await all_elements.count()
                                # Check each element for exact match
                                # IMPORTANT: We want exact matches only, not partial matches like "My issues" when looking for "Issues"
                                for i in range(count):
                                    element = all_elements.nth(i)
                                    try:
                                        element_text = await element.inner_text()
                                        # Normalize: strip whitespace and convert to lowercase
                                        normalized_element_text = element_text.strip().lower()
                                        normalized_search_text = text.strip().lower()
                                        
                                        # Check if it's an exact match (must be exactly equal, not just containing)
                                        # This ensures "Issues" matches "Issues" but NOT "My issues"
                                        if normalized_element_text == normalized_search_text:
                                            if await element.is_visible():
                                                exists = True
                                                locator = element  # Use the exact match element
                                                print(f"  Found exact text match: '{text}' (element text: '{element_text.strip()}')")
                                                break
                                        else:
                                            # Debug: log what we're comparing (only for first few to avoid spam)
                                            if i < 3:
                                                print(f"  Checking element {i}: '{element_text.strip()}' vs '{text}' (normalized: '{normalized_element_text}' vs '{normalized_search_text}')")
                                    except:
                                        continue
                                # If no exact match found, fall back to first partial match
                                if not exists:
                                    locator = self.page.locator(f"text=/{text}/i").first
                                    exists = await locator.count() > 0 and await locator.is_visible()
                            except:
                                # Fallback to simple text match
                                locator = self.page.locator(f"text={text}").first
                                exists = await locator.count() > 0 and await locator.is_visible()
                            
                            # Store failed text for context extraction in fallback (for else if_element_exists)
                            if not exists:
                                self.previous_failed_text_selector = text
                            else:
                                # Clear it if we found a match
                                self.previous_failed_text_selector = None
                        elif selector.startswith('symbol='):
                            symbol = selector.replace('symbol=', '')
                            # For symbols, use context-aware detection
                            exists = False
                            locator = None
                            try:
                                # Extract context from multiple sources
                                context_keywords = []
                                intended_button_text = None  # Full intended button text if available
                                
                                # Priority 1: Extract context from previous failed text selector (most reliable)
                                if self.previous_failed_text_selector:
                                    # Remove symbol and extract meaningful words
                                    text_without_symbol = self.previous_failed_text_selector.replace(symbol, '').strip()
                                    if text_without_symbol:
                                        intended_button_text = text_without_symbol
                                        # Extract all meaningful words as context
                                        words = re.findall(r'\b\w+\b', text_without_symbol.lower())
                                        context_keywords.extend([w for w in words if len(w) > 2])  # Skip short words
                                
                                # Priority 2: Extract from goal (generalized - extract all meaningful words)
                                if not context_keywords:
                                    goal_lower = goal.lower() if goal else ''
                                    # Extract all meaningful words from goal, not just hardcoded keywords
                                    goal_words = re.findall(r'\b\w+\b', goal_lower)
                                    # Filter out common stop words and keep meaningful action/object words
                                    stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those', 'open', 'click', 'press', 'select', 'choose', 'new'}
                                    context_keywords = [w for w in goal_words if w not in stop_words and len(w) > 2]
                                
                                # Priority 3: Use URL state for more accurate context
                                try:
                                    url_state = await self._get_url_state()
                                    if url_state.get('is_issue') and 'issue' not in context_keywords:
                                        context_keywords.append('issue')
                                    if url_state.get('is_project') and 'project' not in context_keywords:
                                        context_keywords.append('project')
                                    if url_state.get('is_view') and 'view' not in context_keywords:
                                        context_keywords.append('view')
                                except:
                                    pass
                                
                                # Priority 4: Fallback to page content if URL state doesn't provide context
                                if not context_keywords:
                                    try:
                                        page_text = await self.page.locator('body').inner_text()
                                        page_text_lower = page_text.lower()
                                        # Extract meaningful words from page content
                                        page_words = re.findall(r'\b\w+\b', page_text_lower)
                                        # Look for common action/object words
                                        common_objects = ['issue', 'project', 'task', 'view', 'team', 'workspace', 'member', 'label', 'milestone']
                                        for obj in common_objects:
                                            if obj in page_words and obj not in context_keywords:
                                                context_keywords.append(obj)
                                    except:
                                        pass
                                
                                # Use context-aware symbol detection with intended button text
                                try:
                                    await self._click_symbol_element(symbol, context_keywords=context_keywords, intended_button_text=intended_button_text)
                                    exists = True
                                    locator = None  # Already clicked
                                    print(f"  Found and clicked symbol: '{symbol}'")
                                except:
                                    exists = False
                            except Exception as e:
                                exists = False
                                # Don't print error here - it's expected that symbol might not exist
                        elif len(selector) == 1 and selector in ['+', '×', '−', '÷', '•', '·', '…', '→', '←', '↑', '↓', '✓', '✗', '★', '☆', '⚙', '⚡']:
                            # Single character that's likely a symbol
                            # Infer context from step goal or page content
                            context_keywords = []
                            try:
                                # Use the goal parameter that's already available
                                goal_lower = goal.lower() if goal else ''
                                if 'issue' in goal_lower:
                                    context_keywords.append('issue')
                                if 'project' in goal_lower:
                                    context_keywords.append('project')
                                if 'task' in goal_lower:
                                    context_keywords.append('task')
                            except:
                                pass
                            
                            try:
                                await self._click_symbol_element(selector, context_keywords=context_keywords)
                                exists = True
                                locator = None  # Symbol click already happened
                                print(f"  Found and clicked symbol: '{selector}'")
                            except:
                                exists = False
                        else:
                            locator = self.page.locator(selector).first
                            exists = await locator.count() > 0 and await locator.is_visible()
                        
                        if exists:
                            # If element exists and hasn't been clicked yet (symbol clicks happen above), try to click it
                            # This is useful for navigation elements like "Projects", "New Project", etc.
                            # If clicking fails, that's okay - we'll still proceed to the next step
                            clicked_something = False
                            if locator is not None:
                                try:
                                    await locator.scroll_into_view_if_needed(timeout=3000)
                                    await locator.click(timeout=5000)
                                    print(f"  Clicked element: {selector}")
                                    clicked_something = True
                                    # Wait a bit for navigation/UI to update
                                    await self.page.wait_for_timeout(1000)
                                except Exception as click_error:
                                    # If clicking fails, that's okay - maybe it's not clickable or already clicked
                                    # The element exists, which is what we're checking for
                                    pass
                            else:
                                # Symbol was already clicked above, just wait a bit
                                clicked_something = True
                                await self.page.wait_for_timeout(1000)
                            
                            # Capture screenshot after clicking (unless it's a login step)
                            if clicked_something:
                                await self._capture_screenshot_after_action(step_number, goal, task_name, "click")
                            
                            return {'skip': True, 'step': target_step}
                        else:
                            return {'condition': True, 'result': False}
                    except:
                        return {'condition': True, 'result': False}
            
            elif processed_action.startswith('else') or processed_action.startswith('else_skip_to_step(') or processed_action.startswith('else proceed_to_step('):
                # Support: else proceed_to_step(N) or else_skip_to_step(N)
                match = re.search(r"proceed_to_step\((\d+)\)|skip_to_step\((\d+)\)", processed_action)
                if match:
                    step_num = int(match.group(1) or match.group(2))
                    return {'skip': True, 'step': step_num}
                # If no step number, just continue (this is the else branch)
                return {'condition': True, 'result': True}
            
            elif processed_action.startswith('type('):
                match = re.search(r"type\('([^']+)',\s*'([^']*)'\)", processed_action)
                if match:
                    selector = match.group(1)
                    text = match.group(2)
                    
                    # Determine field type from selector to help find the right field
                    is_textarea_selector = selector.lower().startswith('textarea') or 'textarea' in selector.lower()
                    is_description_field = 'description' in text.lower() or 'description' in selector.lower()
                    
                    # Check if we're about to type into email/password fields - if so, check for login page first
                    is_email_or_password = ('email' in selector.lower() or 'password' in selector.lower() or 
                                           '<email>' in text.lower() or '<password>' in text.lower())
                    if is_email_or_password and await self.is_login_page():
                        # This will be handled by the execute_plan loop, but we can also check here
                        # The login detection in execute_plan should catch this before we get here
                        pass
                    
                    # Try multiple strategies for typing with fallbacks
                    typed = False
                    try:
                        # First try: click to focus, clear, then fill (more reliable)
                        locator = self.page.locator(selector).first
                        await locator.click(timeout=5000)
                        await self.page.wait_for_timeout(200)
                        # Clear existing content and type
                        await locator.fill(text)
                        # Mark this field as used
                        field_id = await locator.evaluate('el => el.getBoundingClientRect().top + "," + el.getBoundingClientRect().left')
                        used_input_fields.append(field_id)
                        typed = True
                    except Exception as e:
                        # Second try: direct fill
                        try:
                            locator = self.page.locator(selector).first
                            await self.page.fill(selector, text)
                            # Mark this field as used
                            field_id = await locator.evaluate('el => el.getBoundingClientRect().top + "," + el.getBoundingClientRect().left')
                            used_input_fields.append(field_id)
                            typed = True
                        except Exception as e2:
                            # Third try: click first, then fill
                            try:
                                locator = self.page.locator(selector).first
                                await self.page.click(selector, timeout=5000)
                                await self.page.wait_for_timeout(300)
                                await self.page.fill(selector, text)
                                # Mark this field as used
                                field_id = await locator.evaluate('el => el.getBoundingClientRect().top + "," + el.getBoundingClientRect().left')
                                used_input_fields.append(field_id)
                                typed = True
                            except Exception as e3:
                                # Fourth try: find input by position or type (including textarea and contenteditable)
                                if 'input' in selector.lower() or 'textarea' in selector.lower() or 'nth-of-type' in selector or 'contenteditable' in selector.lower():
                                    print(f"  Trying fallback: finding input/textarea/contenteditable by position...")
                                    
                                    # Extract nth-of-type number from selector if present
                                    nth_match = re.search(r':nth-of-type\((\d+)\)', selector)
                                    target_nth = int(nth_match.group(1)) if nth_match else None
                                    
                                    # Try modals/dialogs first, then forms, then anywhere
                                    # Also try inputs without explicit type="text" and contenteditable divs
                                    # Build selectors that skip already-used fields
                                    base_selectors = [
                                        '[role="dialog"] [contenteditable="true"]',
                                        '[role="modal"] [contenteditable="true"]',
                                        '[contenteditable="true"]',
                                        '[role="dialog"] input:not([type="button"]):not([type="submit"]):not([type="hidden"])',
                                        '[role="modal"] input:not([type="button"]):not([type="submit"]):not([type="hidden"])',
                                        'form input:not([type="button"]):not([type="submit"]):not([type="hidden"])',
                                        'textarea',
                                        'input:not([type="button"]):not([type="submit"]):not([type="hidden"])',
                                        'input[type="text"]',
                                    ]
                                    
                                    # Try each selector, finding the appropriate unused field
                                    for base_sel in base_selectors:
                                        try:
                                            all_fields = self.page.locator(base_sel)
                                            count = await all_fields.count()
                                            if count > 0:
                                                # If nth-of-type is specified, use that specific field
                                                if target_nth is not None and target_nth <= count:
                                                    field = all_fields.nth(target_nth - 1)  # nth-of-type is 1-indexed
                                                    field_id = await field.evaluate('el => el.getBoundingClientRect().top + "," + el.getBoundingClientRect().left')
                                                    if field_id not in used_input_fields:
                                                        await field.click(timeout=2000)
                                                        await self.page.wait_for_timeout(200)
                                                        is_contenteditable = await field.evaluate('el => el.contentEditable === "true" || el.hasAttribute("contenteditable")')
                                                        if is_contenteditable:
                                                            await field.evaluate('el => el.textContent = ""')
                                                            await self.page.keyboard.type(text, delay=50)
                                                        else:
                                                            await field.fill(text)
                                                        used_input_fields.append(field_id)
                                                        typed = True
                                                        print(f"  Successfully typed into field at position {target_nth}")
                                                        break
                                                else:
                                                    # Find the appropriate unused field
                                                    # For textarea/description fields, prefer fields that are lower on the page and larger
                                                    field_candidates = []
                                                    for i in range(count):
                                                        field = all_fields.nth(i)
                                                        field_id = await field.evaluate('el => el.getBoundingClientRect().top + "," + el.getBoundingClientRect().left')
                                                        if field_id not in used_input_fields:
                                                            # Get field position and size
                                                            rect = await field.evaluate('el => ({top: el.getBoundingClientRect().top, left: el.getBoundingClientRect().left, height: el.getBoundingClientRect().height, width: el.getBoundingClientRect().width})')
                                                            field_candidates.append({
                                                                'index': i,
                                                                'field': field,
                                                                'id': field_id,
                                                                'top': rect['top'],
                                                                'height': rect['height'],
                                                                'area': rect['height'] * rect['width']
                                                            })
                                                    
                                                    if field_candidates:
                                                        # If looking for textarea/description, prefer fields that are lower and larger
                                                        if is_textarea_selector or is_description_field:
                                                            # Sort by: first by top position (lower = higher priority), then by area (larger = higher priority)
                                                            field_candidates.sort(key=lambda x: (x['top'], -x['area']))
                                                        else:
                                                            # For other fields, prefer fields that are higher on the page
                                                            field_candidates.sort(key=lambda x: x['top'])
                                                        
                                                        # Use the best candidate
                                                        best_candidate = field_candidates[0]
                                                        field = best_candidate['field']
                                                        field_id = best_candidate['id']
                                                        await field.click(timeout=2000)
                                                        await self.page.wait_for_timeout(200)
                                                        is_contenteditable = await field.evaluate('el => el.contentEditable === "true" || el.hasAttribute("contenteditable")')
                                                        if is_contenteditable:
                                                            await field.evaluate('el => el.textContent = ""')
                                                            await self.page.keyboard.type(text, delay=50)
                                                        else:
                                                            await field.fill(text)
                                                        used_input_fields.append(field_id)
                                                        typed = True
                                                        print(f"  Successfully typed into unused field (position {best_candidate['index']+1})")
                                                if typed:
                                                    break
                                        except:
                                            continue
                                
                                if not typed:
                                    print(f"  Warning: Could not type into selector '{selector}'")
                                    print(f"  Tip: The input field may not exist. Trying any visible text input or textarea...")
                                    # Last resort: try any visible text input or textarea (exclude buttons)
                                    try:
                                        # First, try contenteditable divs (many modern apps like Linear use these)
                                        try:
                                            contenteditable_selectors = [
                                                '[role="dialog"] [contenteditable="true"]:visible',
                                                '[role="modal"] [contenteditable="true"]:visible',
                                                'form [contenteditable="true"]:visible',
                                                '[contenteditable="true"]:visible',
                                                '[contenteditable]:visible',  # Some apps don't set it to "true"
                                            ]
                                            for contenteditable_sel in contenteditable_selectors:
                                                try:
                                                    contenteditables = self.page.locator(contenteditable_sel)
                                                    count = await contenteditables.count()
                                                    if count > 0:
                                                        contenteditable = contenteditables.first
                                                        await contenteditable.click(timeout=2000)
                                                        await self.page.wait_for_timeout(200)
                                                        # Clear and type into contenteditable
                                                        await contenteditable.evaluate('el => el.textContent = ""')
                                                        await self.page.keyboard.type(text, delay=50)
                                                        typed = True
                                                        print(f"  Successfully typed into contenteditable element")
                                                        break
                                                except:
                                                    continue
                                        except:
                                            pass
                                        
                                        # Try textarea (common for search boxes like Google, and also in modals)
                                        if not typed:
                                            try:
                                                # Look for textareas in modals/dialogs first, then anywhere
                                                textarea_selectors = [
                                                    '[role="dialog"] textarea:visible',
                                                    '[role="modal"] textarea:visible',
                                                    'form textarea:visible',
                                                    'textarea:visible'
                                                ]
                                                for textarea_sel in textarea_selectors:
                                                    try:
                                                        textareas = self.page.locator(textarea_sel)
                                                        count = await textareas.count()
                                                        if count > 0:
                                                            # If looking for description field, prefer textareas that are lower and larger
                                                            if is_textarea_selector or is_description_field:
                                                                # Collect all unused textareas with their positions
                                                                candidates = []
                                                                for i in range(count):
                                                                    textarea = textareas.nth(i)
                                                                    field_id = await textarea.evaluate('el => el.getBoundingClientRect().top + "," + el.getBoundingClientRect().left')
                                                                    if field_id not in used_input_fields:
                                                                        rect = await textarea.evaluate('el => ({top: el.getBoundingClientRect().top, height: el.getBoundingClientRect().height, width: el.getBoundingClientRect().width})')
                                                                        candidates.append({
                                                                            'textarea': textarea,
                                                                            'id': field_id,
                                                                            'top': rect['top'],
                                                                            'area': rect['height'] * rect['width']
                                                                        })
                                                                if candidates:
                                                                    # Sort by position (lower = higher priority) and size (larger = higher priority)
                                                                    candidates.sort(key=lambda x: (x['top'], -x['area']))
                                                                    textarea = candidates[0]['textarea']
                                                                    field_id = candidates[0]['id']
                                                                else:
                                                                    textarea = textareas.first
                                                                    field_id = await textarea.evaluate('el => el.getBoundingClientRect().top + "," + el.getBoundingClientRect().left')
                                                            else:
                                                                textarea = textareas.first
                                                                field_id = await textarea.evaluate('el => el.getBoundingClientRect().top + "," + el.getBoundingClientRect().left')
                                                            
                                                            if field_id not in used_input_fields:
                                                                await textarea.click(timeout=2000)
                                                                await self.page.wait_for_timeout(200)
                                                                await textarea.fill(text)
                                                                used_input_fields.append(field_id)
                                                                typed = True
                                                                print(f"  Successfully typed into textarea")
                                                                break
                                                    except:
                                                        continue
                                            except:
                                                pass
                                        
                                        if not typed:
                                            # Try text inputs, excluding buttons and submit inputs
                                            # Look in modals/dialogs first, then forms, then anywhere
                                            # Also try inputs without explicit type (many inputs don't have type="text")
                                            input_selectors = [
                                                '[role="dialog"] input:not([type="button"]):not([type="submit"]):not([type="hidden"]):visible',
                                                '[role="modal"] input:not([type="button"]):not([type="submit"]):not([type="hidden"]):visible',
                                                'form input:not([type="button"]):not([type="submit"]):not([type="hidden"]):visible',
                                                'input:not([type="button"]):not([type="submit"]):not([type="hidden"]):visible',
                                                '[role="dialog"] input[type="text"]:visible',
                                                '[role="modal"] input[type="text"]:visible',
                                                'form input[type="text"]:visible',
                                                'input[type="text"]:visible',
                                                '[role="dialog"] input[type="search"]:visible',
                                                '[role="modal"] input[type="search"]:visible',
                                                'form input[type="search"]:visible',
                                                'input[type="search"]:visible',
                                                '[role="dialog"] input[type="email"]:visible',
                                                '[role="modal"] input[type="email"]:visible',
                                                'form input[type="email"]:visible',
                                                'input[type="email"]:visible',
                                            ]
                                            for input_sel in input_selectors:
                                                try:
                                                    all_fields = self.page.locator(input_sel)
                                                    count = await all_fields.count()
                                                    if count > 0:
                                                        # Collect all unused fields with their properties
                                                        candidates = []
                                                        for i in range(count):
                                                            field = all_fields.nth(i)
                                                            field_id = await field.evaluate('el => el.getBoundingClientRect().top + "," + el.getBoundingClientRect().left')
                                                            if field_id not in used_input_fields:
                                                                input_type = await field.get_attribute('type')
                                                                if input_type is None or input_type in ['text', 'search', 'email']:
                                                                    rect = await field.evaluate('el => ({top: el.getBoundingClientRect().top, height: el.getBoundingClientRect().height, width: el.getBoundingClientRect().width})')
                                                                    candidates.append({
                                                                        'field': field,
                                                                        'id': field_id,
                                                                        'top': rect['top']
                                                                    })
                                                        
                                                        if candidates:
                                                            # For description fields, prefer fields that are lower on the page
                                                            if is_description_field:
                                                                candidates.sort(key=lambda x: x['top'])  # Lower = higher priority
                                                            else:
                                                                candidates.sort(key=lambda x: x['top'])  # Higher = higher priority for name fields
                                                            
                                                            best_candidate = candidates[0]
                                                            field = best_candidate['field']
                                                            field_id = best_candidate['id']
                                                            await field.click(timeout=2000)
                                                            await self.page.wait_for_timeout(200)
                                                            await field.fill(text)
                                                            used_input_fields.append(field_id)
                                                            typed = True
                                                            print(f"  Successfully typed into unused field")
                                                            break
                                                except:
                                                    continue
                                            
                                            if not typed:
                                                # Last resort: try typing directly with keyboard (might work if something is focused)
                                                print(f"  Last resort: trying keyboard typing...")
                                                try:
                                                    # Try to find any focusable element in the modal and type there
                                                    focusable = self.page.locator('[role="dialog"] input, [role="dialog"] textarea, [role="dialog"] [contenteditable], [role="modal"] input, [role="modal"] textarea, [role="modal"] [contenteditable]').first
                                                    if await focusable.count() > 0:
                                                        await focusable.click(timeout=2000)
                                                        await self.page.wait_for_timeout(300)
                                                        await self.page.keyboard.type(text, delay=50)
                                                        typed = True
                                                        print(f"  Successfully typed using keyboard")
                                                except:
                                                    # If all else fails, just try typing - maybe something is already focused
                                                    try:
                                                        await self.page.keyboard.type(text, delay=50)
                                                        typed = True
                                                        print(f"  Typed text using keyboard (element may have been focused)")
                                                    except:
                                                        raise Exception("No visible text inputs, textareas, or contenteditable elements found, and keyboard typing failed")
                                    except Exception as e3:
                                        raise Exception(f"Could not type into '{selector}' or any fallback input: {e3}")
                    
                    if typed:
                        # Wait a bit for autocomplete/suggestions to appear
                        await self.page.wait_for_timeout(1000)
                        # Capture screenshot after typing (unless it's a login step)
                        await self._capture_screenshot_after_action(step_number, goal, task_name, "type")
            
            elif processed_action.startswith('click('):
                match = re.search(r"click\('([^']+)'\)", processed_action)
                if match:
                    selector = match.group(1)
                    clicked = False
                    
                    # Handle selectors like '[role="dialog"] text=Button' - extract text and scope to dialog
                    # Match text= followed by text until end of string or next quote/space after a word boundary
                    dialog_text_match = re.search(r'\[role=["\']dialog["\']\]\s+text=([^\'"]+?)(?:\'|")', selector)
                    if not dialog_text_match:
                        # Try without quote at end
                        dialog_text_match = re.search(r'\[role=["\']dialog["\']\]\s+text=([^\'"]+)', selector)
                    if dialog_text_match:
                        text_to_find = dialog_text_match.group(1).strip()
                        try:
                            # Try to find text within dialog first - use exact text matching
                            dialog_locator = self.page.locator('[role="dialog"]')
                            if await dialog_locator.count() > 0:
                                # Look for buttons/clickable elements with this exact text
                                # First try buttons specifically
                                button_locator = dialog_locator.locator(f'button:has-text("{text_to_find}"), [role="button"]:has-text("{text_to_find}")')
                                if await button_locator.count() > 0:
                                    # Check all buttons and find the one that matches exactly and doesn't contain "draft"
                                    for i in range(await button_locator.count()):
                                        btn = button_locator.nth(i)
                                        try:
                                            btn_text = await btn.inner_text()
                                            btn_text_normalized = btn_text.strip().lower()
                                            text_normalized = text_to_find.strip().lower()
                                            # Must match the text and not contain "draft"
                                            if text_normalized in btn_text_normalized and 'draft' not in btn_text_normalized:
                                                if await btn.is_visible():
                                                    await btn.click(timeout=5000)
                                                    clicked = True
                                                    print(f"  Clicked '{text_to_find}' button within dialog (found: '{btn_text}')")
                                                    break
                                        except:
                                            continue
                                    if clicked:
                                        pass  # Already clicked
                                    else:
                                        # Fallback: try text-based click helper which has better matching
                                        await self._click_text_element(text_to_find)
                                        clicked = True
                                        print(f"  Clicked '{text_to_find}' within dialog using text helper")
                        except Exception as e:
                            # Fall through to try regular text click
                            pass
                    
                    # Handle text-based clicks and OR conditions
                    if not clicked and ' OR ' in selector:
                        # Try first selector, if fails try second
                        selectors = [s.strip() for s in selector.split(' OR ')]
                        last_error = None
                        for sel in selectors:
                            try:
                                if sel.startswith("text="):
                                    text = sel.replace("text=", "")
                                    await self._click_text_element(text)
                                else:
                                    locator = self.page.locator(sel).first
                                    await self.page.click(sel, timeout=3000)
                                clicked = True
                                break
                            except Exception as e:
                                last_error = e
                                continue
                        if not clicked:
                            print(f"  Warning: Could not click any of: {', '.join(selectors)}")
                            print(f"  Tip: The selectors may not exist on this page. Check the screenshot.")
                            raise Exception(f"Could not click any of: {', '.join(selectors)}. Last error: {last_error}")
                    elif selector.startswith("text="):
                        text = selector.replace("text=", "")
                        try:
                            await self._click_text_element(text)
                            clicked = True
                        except Exception as e:
                            print(f"  Warning: Could not click text '{text}'")
                            print(f"  Tip: The text may not be visible or may be spelled differently.")
                            raise
                    elif selector.startswith("symbol="):
                        # Support for symbol-based clicks like symbol=+ or symbol=×
                        symbol = selector.replace("symbol=", "")
                        # Infer context from step goal (generalized - extract all meaningful words)
                        context_keywords = []
                        try:
                            goal_lower = goal.lower() if goal else ''
                            # Extract all meaningful words from goal, not just hardcoded keywords
                            goal_words = re.findall(r'\b\w+\b', goal_lower)
                            # Filter out common stop words and keep meaningful action/object words
                            stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those', 'open', 'click', 'press', 'select', 'choose', 'new'}
                            context_keywords = [w for w in goal_words if w not in stop_words and len(w) > 2]
                        except:
                            pass
                        
                        try:
                            await self._click_symbol_element(symbol, context_keywords=context_keywords)
                            clicked = True
                        except Exception as e:
                            print(f"  Warning: Could not click symbol '{symbol}'")
                            print(f"  Tip: The symbol may not be visible or may be in a different location.")
                            raise
                    elif len(selector) == 1 and selector in ['+', '×', '−', '÷', '•', '·', '…', '→', '←', '↑', '↓', '✓', '✗', '★', '☆', '⚙', '⚡', '🔍', '📝', '➕', '✏', '🗑', '⭐']:
                        # Single character that's likely a symbol - try clicking it
                        # Infer context from step goal (generalized - extract all meaningful words)
                        context_keywords = []
                        try:
                            goal_lower = goal.lower() if goal else ''
                            # Extract all meaningful words from goal, not just hardcoded keywords
                            goal_words = re.findall(r'\b\w+\b', goal_lower)
                            # Filter out common stop words and keep meaningful action/object words
                            stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'as', 'is', 'are', 'was', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should', 'could', 'may', 'might', 'must', 'can', 'this', 'that', 'these', 'those', 'open', 'click', 'press', 'select', 'choose', 'new'}
                            context_keywords = [w for w in goal_words if w not in stop_words and len(w) > 2]
                        except:
                            pass
                        
                        try:
                            await self._click_symbol_element(selector, context_keywords=context_keywords)
                            clicked = True
                        except Exception as e:
                            # Fall back to regular selector
                            try:
                                locator = self.page.locator(selector).first
                                await self.page.click(selector, timeout=10000)
                                clicked = True
                            except:
                                print(f"  Warning: Could not click symbol '{selector}'")
                                raise Exception(f"Could not click symbol '{selector}'")
                    else:
                        # Try the selector, with fallbacks for common patterns
                        try:
                            locator = self.page.locator(selector).first
                            await self.page.click(selector, timeout=10000)
                            clicked = True
                        except Exception as e:
                            # If selector contains 'text=' but wasn't caught earlier, try text-based click
                            if 'text=' in selector.lower() and not clicked:
                                # Extract text from patterns like '[role="dialog"] text=Button' or 'text=Button'
                                # Match text= followed by text until end of string or quote
                                text_match = re.search(r'text=([^\'"]+?)(?:\'|")', selector)
                                if not text_match:
                                    # Try without quote at end
                                    text_match = re.search(r'text=([^\s\'"]+)', selector)
                                if text_match:
                                    text_to_click = text_match.group(1).strip()
                                    print(f"  Trying fallback: clicking text '{text_to_click}'...")
                                    try:
                                        # First try to find buttons with this exact text in dialog, filtering out "draft"
                                        dialog_locator = self.page.locator('[role="dialog"]')
                                        if await dialog_locator.count() > 0:
                                            buttons = dialog_locator.locator('button, [role="button"]')
                                            count = await buttons.count()
                                            for i in range(count):
                                                btn = buttons.nth(i)
                                                try:
                                                    btn_text = await btn.inner_text()
                                                    btn_text_normalized = btn_text.strip().lower()
                                                    text_normalized = text_to_click.strip().lower()
                                                    # Must contain the text and NOT contain "draft"
                                                    if text_normalized in btn_text_normalized and 'draft' not in btn_text_normalized:
                                                        if await btn.is_visible():
                                                            await btn.click(timeout=3000)
                                                            clicked = True
                                                            print(f"  Clicked button with text '{btn_text}' (matched '{text_to_click}')")
                                                            break
                                                except:
                                                    continue
                                        
                                        # If that didn't work, use the text helper
                                        if not clicked:
                                            await self._click_text_element(text_to_click)
                                            clicked = True
                                    except:
                                        pass
                            
                            # Try fallback strategies
                            if not clicked and 'input' in selector.lower():
                                print(f"  Trying fallback: clicking first input field...")
                                try:
                                    locator = self.page.locator('input[type="text"]:first-of-type').first
                                    await self.page.click('input[type="text"]:first-of-type', timeout=3000)
                                    clicked = True
                                except:
                                    pass
                            elif not clicked and 'button' in selector.lower():
                                print(f"  Trying fallback: clicking first button...")
                                try:
                                    locator = self.page.locator('button:first-of-type').first
                                    await self.page.click('button:first-of-type', timeout=3000)
                                    clicked = True
                                except:
                                    # Try pressing Enter as last resort for form buttons
                                    print(f"  Trying fallback: pressing Enter key...")
                                    try:
                                        await self.page.keyboard.press('Enter')
                                        clicked = True
                                    except:
                                        pass
                            
                            # If selector contains action keywords (create, submit, etc.), try finding button by text
                            if not clicked:
                                action_keywords = ['create', 'submit', 'save', 'add', 'confirm', 'send', 'post', 'publish']
                                for keyword in action_keywords:
                                    if keyword in selector.lower():
                                        print(f"  Trying fallback: looking for button with '{keyword}' text...")
                                        try:
                                            # First, try to extract the full text from the selector if it contains text=
                                            # Match text= followed by text until end of string or quote
                                            full_text_match = re.search(r'text=([^\'"]+?)(?:\'|")', selector)
                                            if not full_text_match:
                                                # Try without quote at end
                                                full_text_match = re.search(r'text=([^\s\'"]+)', selector)
                                            if full_text_match:
                                                full_text = full_text_match.group(1).strip()
                                                # Try exact text match first (case-insensitive)
                                                exact_selectors = [
                                                    f'[role="dialog"] button:has-text("{full_text}")',
                                                    f'[role="dialog"] [role="button"]:has-text("{full_text}")',
                                                    f'button:has-text("{full_text}")',
                                                    f'[role="button"]:has-text("{full_text}")',
                                                ]
                                                for btn_sel in exact_selectors:
                                                    try:
                                                        all_buttons = self.page.locator(btn_sel)
                                                        count = await all_buttons.count()
                                                        if count > 0:
                                                            # Check all buttons and find the best match
                                                            for i in range(count):
                                                                btn = all_buttons.nth(i)
                                                                try:
                                                                    if await btn.is_visible():
                                                                        btn_text = await btn.inner_text()
                                                                        btn_text_normalized = btn_text.strip().lower()
                                                                        full_text_normalized = full_text.strip().lower()
                                                                        # Must contain the full text and NOT contain "draft"
                                                                        if full_text_normalized in btn_text_normalized and 'draft' not in btn_text_normalized:
                                                                            await btn.click(timeout=3000)
                                                                            clicked = True
                                                                            print(f"  Found and clicked button with matching text: '{btn_text}'")
                                                                            break
                                                                except:
                                                                    continue
                                                            if clicked:
                                                                break
                                                    except:
                                                        continue
                                                if clicked:
                                                    break
                                            
                                            # If exact match didn't work, try keyword-based search but filter out unwanted buttons
                                            if not clicked:
                                                button_selectors = [
                                                    f'[role="dialog"] button:has-text("{keyword}")',
                                                    f'[role="dialog"] [role="button"]:has-text("{keyword}")',
                                                    f'button:has-text("{keyword}")',
                                                    f'[role="button"]:has-text("{keyword}")',
                                                ]
                                                for btn_sel in button_selectors:
                                                    try:
                                                        all_buttons = self.page.locator(btn_sel)
                                                        count = await all_buttons.count()
                                                        if count > 0:
                                                            # Find the best button - prefer ones that don't contain "draft", "cancel", etc.
                                                            best_button = None
                                                            for i in range(count):
                                                                btn = all_buttons.nth(i)
                                                                try:
                                                                    if await btn.is_visible():
                                                                        btn_text = await btn.inner_text()
                                                                        btn_text_lower = btn_text.lower()
                                                                        # Skip buttons with unwanted keywords
                                                                        if any(unwanted in btn_text_lower for unwanted in ['draft', 'cancel', 'close', 'back']):
                                                                            continue
                                                                        # Prefer buttons that contain the keyword
                                                                        if keyword.lower() in btn_text_lower:
                                                                            best_button = btn
                                                                            # If it's an exact match or close match, use it immediately
                                                                            if keyword.lower() == btn_text_lower.strip().lower() or btn_text_lower.startswith(keyword.lower()):
                                                                                break
                                                                except:
                                                                    continue
                                                            
                                                            if best_button:
                                                                await best_button.click(timeout=3000)
                                                                clicked = True
                                                                btn_text = await best_button.inner_text()
                                                                print(f"  Found and clicked button: '{btn_text}'")
                                                                break
                                                    except:
                                                        continue
                                                if clicked:
                                                    break
                                        except:
                                            pass
                            
                            if not clicked:
                                print(f"  Warning: Could not click selector '{selector}'")
                                print(f"  Tip: This selector may not exist. Try using text-based selectors like click('text=Button Label')")
                                raise Exception(f"Could not click selector '{selector}' or fallback")
                    
                    if clicked:
                        # Check if this is a submit/action button (Create, Save, Submit, etc.)
                        is_action_button = any(keyword in selector.lower() for keyword in [
                            'create', 'save', 'submit', 'add', 'confirm', 'send', 'post', 'publish'
                        ])
                        
                        if is_action_button:
                            # For action buttons, check URL change as validation
                            url_before = self.page.url
                            await self.page.wait_for_timeout(2000)  # Wait for navigation/state change
                            url_after = self.page.url
                            
                            if url_before != url_after:
                                url_state = await self._get_url_state()
                                print(f"  Action button clicked - URL changed (navigation confirmed)")
                                # URL change often indicates successful submission
                                if url_state.get('is_create') or '/new' in url_state.get('url', ''):
                                    print(f"  Navigated to create/new page")
                                elif '/edit' in url_state.get('url', '') or '/update' in url_state.get('url', ''):
                                    print(f"  Navigated to edit/update page")
                                else:
                                    print(f"  URL state: {url_after[:80]}...")
                            else:
                                # No URL change - might be modal/form or same-page update
                                # Check for modal/form elements
                                try:
                                    await self.page.wait_for_selector('input, textarea, [contenteditable], form, [role="dialog"], [role="modal"]', timeout=3000, state='visible')
                                    print(f"  Action button clicked - form/modal appeared")
                                except:
                                    # No modal/form, might be same-page update
                                    print(f"  Action button clicked - same page update")
                        else:
                            # For non-action buttons, wait for modals/forms
                            await self.page.wait_for_timeout(1500)  # Wait for UI to update
                            # After clicking buttons that might open modals/forms, wait for common modal/form elements
                            # This helps with buttons like "New Project", "Create", etc.
                            try:
                                # Wait for common modal/form indicators including contenteditable (with longer timeout for modals)
                                await self.page.wait_for_selector('input, textarea, [contenteditable], form, [role="dialog"], [role="modal"]', timeout=5000, state='visible')
                                # Additional wait to ensure modal content is fully loaded
                                await self.page.wait_for_timeout(500)
                            except:
                                # No modal/form appeared, that's okay - continue anyway
                                await self.page.wait_for_timeout(1000)  # Still wait a bit
                                pass
                        
                        # Capture screenshot after clicking (unless it's a login step)
                        await self._capture_screenshot_after_action(step_number, goal, task_name, "click")
            
            elif processed_action.startswith('press(') or processed_action.startswith('press_key('):
                # Support for keyboard actions like press('Enter'), press('c'), press_key('c')
                match = re.search(r"press(?:|_key)\('([^']+)'\)", processed_action)
                if match:
                    key = match.group(1)
                    
                    # Handle special keys like Enter, Escape, etc.
                    if key.upper() == 'ENTER':
                        # Before pressing Enter, try to find a submit button
                        print(f"  Looking for submit button before pressing Enter...")
                        button_clicked = False
                        # Common submit button texts (generic, not hardcoded)
                        submit_button_texts = [
                            'Create', 'Submit', 'Save', 'Add', 'Confirm', 'Done', 
                            'Finish', 'Apply', 'OK', 'Continue', 'Next', 'Send'
                        ]
                        
                        # Try to find buttons with submit-related text
                        for button_text in submit_button_texts:
                            try:
                                button = self.page.locator(f'button:has-text("{button_text}"), [role="button"]:has-text("{button_text}")').first
                                if await button.count() > 0 and await button.is_visible():
                                    await button.click(timeout=3000)
                                    button_clicked = True
                                    print(f"  Clicked submit button: '{button_text}'")
                                    break
                            except:
                                continue
                        
                        # Also try generic submit button
                        if not button_clicked:
                            try:
                                submit_button = self.page.locator('button[type="submit"], form button[type="submit"]').first
                                if await submit_button.count() > 0 and await submit_button.is_visible():
                                    await submit_button.click(timeout=3000)
                                    button_clicked = True
                                    print(f"  Clicked submit button")
                            except:
                                pass
                        
                        # If no button found, press Enter as fallback
                        if not button_clicked:
                            print(f"  No submit button found, pressing Enter...")
                            await self.page.keyboard.press(key)
                    else:
                        # For single character keys or other keyboard shortcuts
                        # First, try to find a button that might be triggered by this shortcut
                        # (e.g., 'c' might trigger "Create" button)
                        if len(key) == 1 and key.isalpha():
                            print(f"  Pressing keyboard shortcut: '{key}'")
                            # Common keyboard shortcut mappings (generalized)
                            shortcut_actions = {
                                'c': ['create', 'add', 'new'],
                                'n': ['new', 'create'],
                                'a': ['add', 'append'],
                                's': ['save', 'submit'],
                                'e': ['edit'],
                                'd': ['delete'],
                                'f': ['find', 'search'],
                            }
                            
                            # Try to find buttons that might be triggered by this shortcut
                            if key.lower() in shortcut_actions:
                                action_keywords = shortcut_actions[key.lower()]
                                button_found = False
                                for keyword in action_keywords:
                                    try:
                                        # Look for buttons with aria-label or text containing the keyword
                                        button = self.page.locator(f'[aria-label*="{keyword}" i], button:has-text("{keyword}") i, [role="button"]:has-text("{keyword}") i').first
                                        if await button.count() > 0 and await button.is_visible():
                                            await button.click(timeout=3000)
                                            button_found = True
                                            print(f"  Found and clicked button matching shortcut '{key}': '{keyword}'")
                                            break
                                    except:
                                        continue
                                
                                if not button_found:
                                    # If no button found, press the key directly
                                    await self.page.keyboard.press(key)
                                    print(f"  Pressed keyboard shortcut: '{key}'")
                            else:
                                # For other single character keys, press directly
                                await self.page.keyboard.press(key)
                                print(f"  Pressed key: '{key}'")
                        else:
                            # For special keys (Escape, Tab, etc.) or multi-character keys
                            await self.page.keyboard.press(key)
                            print(f"  Pressed key: '{key}'")
                    
                    await self.page.wait_for_timeout(500)
                    # Capture screenshot after pressing key (unless it's a login step)
                    await self._capture_screenshot_after_action(step_number, goal, task_name, "press")
            
            elif processed_action.startswith('assert('):
                match = re.search(r"assert\('([^']+)'\)", processed_action)
                if match:
                    selector = match.group(1)
                    if selector.startswith("text="):
                        text = selector.replace("text=", "")
                        await self.page.wait_for_selector(f"text={text}", timeout=10000)
                    else:
                        await self.page.wait_for_selector(selector, timeout=10000)
                    # Capture screenshot after assertion passes (unless login-related)
                    await self._capture_screenshot_after_action(step_number, goal, task_name, "assert")
            
            elif processed_action.startswith('//'):
                # Comment, skip
                return {'skip': True}
            
            else:
                print(f"  Unknown action format: {processed_action}")
        
        except Exception as error:
            print(f"  Error executing action \"{action}\": {error}")
            # Don't capture screenshot on error - only on successful step completion
            raise
        
        return {'success': True}

    async def _get_url_state(self):
        """Extract meaningful state from URL (generalized for any app)."""
        return await get_url_state(self.page)
    
    async def _wait_for_url_change(self, initial_url, timeout=10000, expected_patterns=None):
        """Wait for URL to change, optionally matching specific patterns."""
        return await wait_for_url_change(self.page, initial_url, timeout, expected_patterns)

    async def execute_plan(self, navigation_plan, task_name, credentials=None):
        if credentials is None:
            credentials = {}
        
        print(f"\nExecuting plan for: {task_name}")
        print(f"Task understanding: {navigation_plan['task_understanding']}\n")

        screenshots = []
        current_step = 0
        login_completed = False
        used_input_fields = []  # Track which input fields have been used in the current step
        previous_url = None  # Track URL changes

        try:
            for step in navigation_plan['ui_navigation_plan']:
                current_step = step['step']
                used_input_fields = []  # Reset for each new step
                
                # Track URL state at start of step
                url_state_before = await self._get_url_state()
                previous_url = self.page.url
                
                print(f"\nStep {step['step']}: {step['goal']}")
                if step.get('notes'):
                    print(f"  Notes: {step['notes']}")

                should_skip = False
                skip_to_step = None

                step_successful = True
                skip_remaining_login_actions = False
                
                # Check for login page at the start of steps that involve login
                step_goal_lower = step.get('goal', '').lower()
                if not login_completed and ('login' in step_goal_lower or 'log in' in step_goal_lower or 'sign in' in step_goal_lower):
                    if await self.is_login_page():
                        await self.wait_for_manual_login()
                        login_completed = True
                        skip_remaining_login_actions = True
                        print(f"  Login completed manually. Skipping remaining login actions in this step.")
                
                for action in step['actions']:
                    # Check for login page before executing actions (but only once per step)
                    if not login_completed and await self.is_login_page():
                        await self.wait_for_manual_login()
                        login_completed = True
                        # After manual login, skip remaining login-related actions in this step
                        skip_remaining_login_actions = True
                        print(f"  Login completed manually. Skipping remaining login actions in this step.")
                    
                    # Check if this is a login-related action
                    # (step_goal_lower is already defined above in the step loop)
                    is_login_step = ('login' in step_goal_lower or 'log in' in step_goal_lower or 'sign in' in step_goal_lower)
                    
                    # Password fields are almost always login-related
                    is_password_field = any(keyword in action.lower() for keyword in [
                        'input[type="password"]',
                        '<password>',
                        "type('input[type=\"password\"]",
                        'type("input[type=\'password\']'
                    ])
                    
                    # Email fields are only login-related if:
                    # 1. They're in a login step, OR
                    # 2. They use placeholder values like <EMAIL>, OR
                    # 3. They're typing into a login form (not a form context like "form input[type='email']")
                    is_email_field = any(keyword in action.lower() for keyword in [
                        'input[type="email"]',
                        '<email>',
                        "type('input[type=\"email\"]",
                        'type("input[type=\'email\']'
                    ])
                    
                    # Check if email field is in a login context
                    is_login_email = False
                    if is_email_field:
                        # If it's in a login step, it's definitely a login email
                        if is_login_step:
                            is_login_email = True
                        # If it uses placeholder values, it's likely a login email
                        elif '<email>' in action.lower() or '<password>' in action.lower():
                            is_login_email = True
                        # If it's typing into a bare email input (not in a form context), it might be login
                        # But if it's in a form context (like "form input[type='email']"), it's probably not login
                        elif "type('input[type=\"email\"]" in action.lower() or "type(\"input[type='email\"]" in action.lower():
                            # Check if it's NOT in a form context (bare input selector suggests login)
                            if 'form' not in action.lower() and 'textarea' not in action.lower():
                                is_login_email = True
                    
                    # Submit button in login step is a login action
                    is_submit_in_login = is_login_step and ('button[type="submit"]' in action.lower() or 
                                                             "click('button[type=\"submit\"]" in action.lower() or
                                                             'click("button[type=\'submit\']' in action.lower())
                    
                    # Combine all login action checks
                    is_login_action = is_password_field or is_login_email or is_submit_in_login
                    
                    # Also check if this is a "Log in" button click in a login step
                    is_login_button_click = is_login_step and (
                        "click('text=Log in" in action.lower() or 
                        'click("text=Log in' in action.lower() or
                        "click('text=Sign in" in action.lower() or
                        'click("text=Sign in' in action.lower() or
                        "click('text=Login" in action.lower() or
                        'click("text=Login' in action.lower()
                    )
                    
                    if is_login_button_click:
                        is_login_action = True
                    
                    # If we're in a login step and login is already completed, skip ALL actions in this step
                    if is_login_step and (login_completed or skip_remaining_login_actions):
                        print(f"  Skipping action in login step (login already completed): {action}")
                        continue
                    
                    # If this is a login action and login is already completed, skip it (fallback for non-login steps)
                    if login_completed or skip_remaining_login_actions:
                        if is_login_action:
                            print(f"  Skipping login action (login already completed): {action}")
                            continue
                    
                    # If this is a login action and we're not on a login page yet, try to get to login page
                    if is_login_action and not login_completed:
                        # Check if we're on a login page
                        if not await self.is_login_page():
                            # Try to find and click "Log in" button to get to login page
                            print(f"  Not on login page yet. Looking for login button...")
                            try:
                                # Try different login button texts
                                login_texts = ['text=Log in', 'text=Sign in', 'text=Login', 'text=Sign In', 'text=Log In']
                                clicked = False
                                for login_text in login_texts:
                                    try:
                                        login_button = self.page.locator(login_text).first
                                        if await login_button.count() > 0 and await login_button.is_visible():
                                            await login_button.click(timeout=3000)
                                            await self.page.wait_for_timeout(2000)  # Wait for login page to load
                                            print(f"  Clicked login button")
                                            clicked = True
                                            break
                                    except:
                                        continue
                            except:
                                pass
                        
                        # Now check if we're on a login page (after clicking or if we were already there)
                        if await self.is_login_page():
                            await self.wait_for_manual_login()
                            login_completed = True
                            skip_remaining_login_actions = True
                            print(f"  Login completed manually. Skipping remaining login actions in this step.")
                            continue  # Skip the typing action since login is done
                    
                    # Track URL before action
                    url_before_action = self.page.url
                    
                    try:
                        result = await self.execute_action(
                            action,
                            step['step'],
                            step['goal'],
                            task_name,
                            credentials,
                            used_input_fields  # Pass the list to track used fields
                        )

                        # Track URL after action and check for navigation
                        await self.page.wait_for_timeout(500)  # Brief wait for URL to update
                        url_after_action = self.page.url
                        
                        # If URL changed, it likely indicates successful navigation
                        if url_before_action != url_after_action:
                            url_state = await self._get_url_state()
                            print(f"  URL changed: {url_before_action[:50]}... → {url_after_action[:50]}...")
                            
                            # Use URL state to infer context for future actions
                            # This helps with symbol detection and button clicks
                            if url_state.get('is_create') or url_state.get('is_view') or url_state.get('is_issue') or url_state.get('is_project'):
                                print(f"  URL indicates state: {', '.join([k for k, v in url_state.items() if v and k != 'url'])}")

                        if result.get('skip') and result.get('step'):
                            skip_to_step = result['step']
                            should_skip = True
                            break
                        
                        if result.get('condition') is True and result.get('result') is False:
                            # Condition not met, might need to skip
                            continue
                    except Exception as action_error:
                        # If action fails, mark step as unsuccessful
                        print(f"  Action failed: {action_error}")
                        print(f"  Continuing with next action...")
                        step_successful = False
                        # Continue to next action instead of stopping
                        continue

                # Capture screenshot only if step completed successfully AND it's a login-related step
                # (For non-login steps, screenshots are captured after each action)
                if step_successful:
                    # Track URL state at end of step for validation
                    url_state_after = await self._get_url_state()
                    if previous_url != self.page.url:
                        print(f"  Step completed - URL changed: {self.page.url[:80]}...")
                        # Log URL state indicators
                        state_indicators = [k for k, v in url_state_after.items() if v and k not in ['url', 'path_parts', 'query_params']]
                        if state_indicators:
                            print(f"  URL state: {', '.join(state_indicators)}")
                    
                    # Only capture end-of-step screenshot for login-related steps
                    if await self._is_login_related_step(step['goal']):
                        screenshot_path = await self.capture_screenshot(
                            step['step'],
                            step['goal'],
                            task_name
                        )
                        screenshots.append({
                            'step': step['step'],
                            'goal': step['goal'],
                            'path': screenshot_path,
                            'url_state': url_state_after
                        })
                        print(f"  Screenshot captured: {screenshot_path}")

                if should_skip and skip_to_step:
                    print(f"  Skipping to step {skip_to_step}")
                    # Find the step to skip to
                    target_step = next(
                        (s for s in navigation_plan['ui_navigation_plan'] if s['step'] == skip_to_step),
                        None
                    )
                    if target_step:
                        current_step = skip_to_step - 1  # Will be incremented in next iteration
                        continue

            print(f"\nTask completed successfully!")
            print(f"\nWaiting 5 seconds before closing automation...")
            await self.page.wait_for_timeout(5000)
            print(f"Closing browser...")
            return {
                'success': True,
                'screenshots': screenshots,
                'task_name': task_name
            }
        except Exception as error:
            print(f"\nError executing plan: {error}")
            return {
                'success': False,
                'error': str(error),
                'screenshots': screenshots,
                'task_name': task_name
            }

