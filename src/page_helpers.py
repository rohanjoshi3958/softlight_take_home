"""Helper functions for page state detection and URL utilities."""

from urllib.parse import urlparse, parse_qs


async def is_login_page(page):
    """Detect if we're on a login page by checking for common login indicators."""
    try:
        # Must have both email/username AND password fields visible to be considered a login page
        has_email_field = False
        has_password_field = False
        
        # Check for email/username fields
        email_indicators = [
            'input[type="email"]',
            'input[name*="email" i]',
            'input[name*="username" i]',
            'input[id*="email" i]',
            'input[id*="username" i]',
            'input[placeholder*="email" i]',
            'input[placeholder*="username" i]'
        ]
        
        for indicator in email_indicators:
            try:
                element = await page.locator(indicator).first
                if await element.is_visible(timeout=500):
                    has_email_field = True
                    break
            except:
                continue
        
        # Check for password field
        password_indicators = [
            'input[type="password"]',
            'input[name*="password" i]',
            'input[id*="password" i]',
            'input[placeholder*="password" i]'
        ]
        
        for indicator in password_indicators:
            try:
                element = await page.locator(indicator).first
                if await element.is_visible(timeout=500):
                    has_password_field = True
                    break
            except:
                continue
        
        # Must have both email and password fields
        if has_email_field and has_password_field:
            return True
        
        # Also check URL for login-related paths (strong indicator)
        url = page.url.lower()
        login_paths = ['/login', '/signin', '/auth', '/sign-in', '/log-in', '/sign-in/']
        if any(path in url for path in login_paths):
            # Even if fields aren't visible yet, URL suggests login page
            return True
            
        return False
    except:
        return False


async def wait_for_manual_login(page, post_login_indicators=None):
    """Pause execution and wait for user to manually log in, then detect when login is complete."""
    if post_login_indicators is None:
        # Common post-login indicators
        post_login_indicators = [
            '[data-test*="dashboard" i]',
            '[data-test*="sidebar" i]',
            '[data-test*="workspace" i]',
            '[class*="dashboard" i]',
            '[class*="sidebar" i]',
            'nav',
            'aside',
            '[aria-label*="menu" i]',
            '[aria-label*="navigation" i]'
        ]
    
    print("\n" + "=" * 60)
    print("LOGIN PAGE DETECTED")
    print("=" * 60)
    print("\nAutomation paused for manual login.")
    print("   Please log in manually in the browser window.")
    print("   The automation will continue automatically once login is detected.")
    print("\n   Press Ctrl+C in the terminal to cancel.\n")
    
    # Wait for URL change or post-login indicators
    initial_url = page.url
    max_wait_time = 300  # 5 minutes max wait
    check_interval = 2  # Check every 2 seconds
    elapsed = 0
    
    while elapsed < max_wait_time:
        await page.wait_for_timeout(check_interval * 1000)
        elapsed += check_interval
        
        current_url = page.url
        
        # Check if URL changed (common after login)
        if current_url != initial_url and 'login' not in current_url.lower() and 'signin' not in current_url.lower():
            # Check if we're no longer on a login page
            if not await is_login_page(page):
                print("\nLogin detected! Continuing automation...\n")
                await page.wait_for_timeout(2000)  # Wait a bit for page to settle
                return True
        
        # Check for post-login indicators
        for indicator in post_login_indicators:
            try:
                element = await page.locator(indicator).first
                if await element.is_visible(timeout=1000):
                    # Double check we're not still on login page
                    if not await is_login_page(page):
                        print("\nLogin detected! Continuing automation...\n")
                        await page.wait_for_timeout(2000)  # Wait a bit for page to settle
                        return True
            except:
                continue
    
    print("\nLogin timeout reached. Continuing anyway...\n")
    return False


async def get_url_state(page):
    """Extract meaningful state from URL (generalized for any app)."""
    try:
        url = page.url.lower()
        # Extract path segments and query params
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]
        query_params = parse_qs(parsed.query)
        
        state = {
            'url': url,
            'path_parts': path_parts,
            'query_params': query_params,
            'is_create': any(keyword in url for keyword in ['/new', '/create', '/add', '/edit']),
            'is_view': any(keyword in url for keyword in ['/view', '/views']),
            'is_issue': any(keyword in url for keyword in ['/issue', '/issues']),
            'is_project': any(keyword in url for keyword in ['/project', '/projects']),
            'is_settings': any(keyword in url for keyword in ['/settings', '/config', '/preferences']),
            'is_login': any(keyword in url for keyword in ['/login', '/signin', '/auth', '/sign-in']),
        }
        return state
    except:
        return {'url': page.url.lower() if page.url else '', 'path_parts': [], 'query_params': {}}


async def wait_for_url_change(page, initial_url, timeout=10000, expected_patterns=None):
    """Wait for URL to change, optionally matching specific patterns."""
    try:
        await page.wait_for_function(
            f"window.location.href !== '{initial_url}'",
            timeout=timeout
        )
        new_url = page.url
        if expected_patterns:
            for pattern in expected_patterns:
                if pattern.lower() in new_url.lower():
                    return True, new_url
        return True, new_url
    except:
        return False, page.url

