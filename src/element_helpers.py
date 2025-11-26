"""Helper functions for clicking text and symbol elements."""

import re


async def click_text_element(page, text):
    """Helper method to click text elements with multiple fallback strategies."""
    # Define common action button synonyms (generalized for any app)
    action_synonyms = {
        'create': ['save', 'submit', 'add', 'confirm', 'done', 'finish', 'apply', 'ok', 'continue', 'next', 'send', 'post', 'publish'],
        'save': ['create', 'submit', 'update', 'confirm', 'done', 'finish', 'apply', 'ok', 'continue', 'next'],
        'submit': ['create', 'save', 'confirm', 'done', 'finish', 'apply', 'ok', 'continue', 'next', 'send'],
        'add': ['create', 'new', 'insert', 'plus'],
        'new': ['create', 'add', 'new'],
        'edit': ['update', 'modify', 'change', 'save'],
        'update': ['save', 'submit', 'confirm', 'apply'],
        'delete': ['remove', 'trash', 'archive'],
        'cancel': ['close', 'dismiss', 'back'],
        'confirm': ['save', 'submit', 'ok', 'yes', 'accept'],
    }
    
    # Normalize the search text
    normalized_search = text.strip().lower()
    
    # Get synonyms for the search text
    synonyms_to_try = []
    if normalized_search in action_synonyms:
        synonyms_to_try = action_synonyms[normalized_search]
    else:
        # Check if any synonym key contains our search text (e.g., "create project" -> "create")
        for key, synonyms in action_synonyms.items():
            if key in normalized_search or normalized_search in key:
                synonyms_to_try = synonyms
                break
    
    # Strategy 1: Find exact text match by checking ALL elements containing the text
    # This is CRITICAL to avoid matching "My issues" when looking for "Issues"
    try:
        # Find all elements that contain the text (case-insensitive)
        all_elements = page.locator(f'text=/{text}/i')
        count = await all_elements.count()
        
        # First pass: Look for exact matches
        exact_matches = []
        for i in range(count):
            element = all_elements.nth(i)
            try:
                element_text = await element.inner_text()
                # Normalize: strip whitespace and convert to lowercase
                normalized_element_text = element_text.strip().lower()
                normalized_search_text = text.strip().lower()
                
                # Check if it's an exact match (must be exactly equal, not just containing)
                if normalized_element_text == normalized_search_text:
                    # Check if it's visible
                    if await element.is_visible():
                        exact_matches.append((i, element, element_text.strip()))
            except:
                continue
        
        # If we found exact matches, use the first one
        if exact_matches:
            idx, element, found_text = exact_matches[0]
            await element.scroll_into_view_if_needed(timeout=3000)
            await element.wait_for(state='visible', timeout=3000)
            await element.click(timeout=5000)
            print(f"  Clicked exact text match: '{text}' (found: '{found_text}')")
            return
    except Exception as e:
        # If this strategy fails, continue to next
        pass
    
    # Strategy 2: Try synonyms if exact match failed (only for action buttons)
    if synonyms_to_try:
        try:
            # Look for buttons with synonym text
            all_buttons = page.locator('button:visible, [role="button"]:visible')
            count = await all_buttons.count()
            for i in range(count):
                button = all_buttons.nth(i)
                try:
                    button_text = await button.inner_text()
                    button_text_lower = button_text.strip().lower()
                    
                    # Check if button text matches any synonym
                    for synonym in synonyms_to_try:
                        if synonym == button_text_lower or synonym in button_text_lower:
                            await button.scroll_into_view_if_needed(timeout=3000)
                            await button.wait_for(state='visible', timeout=3000)
                            await button.click(timeout=5000)
                            print(f"  Clicked synonym button: '{synonym}' (searched for: '{text}', found: '{button_text}')")
                            return
                except:
                    continue
        except:
            pass
    
    # Strategy 3: Partial match (fallback if exact match not found)
    try:
        locator = page.locator(f"text=/{text}/i").first
        await locator.scroll_into_view_if_needed(timeout=3000)
        await locator.wait_for(state='visible', timeout=3000)
        await locator.click(timeout=5000)
        print(f"  Clicked partial text match: '{text}'")
        return
    except:
        pass
    
    # Strategy 4: Try as button with partial text match (e.g., "Create" matches "Create project")
    try:
        buttons = page.locator('button, [role="button"]')
        count = await buttons.count()
        for i in range(count):
            button = buttons.nth(i)
            try:
                button_text = await button.inner_text()
                if text.lower() in button_text.lower():
                    await button.scroll_into_view_if_needed(timeout=3000)
                    await button.wait_for(state='visible', timeout=3000)
                    await button.click(timeout=5000)
                    print(f"  Found button with text containing '{text}': '{button_text}'")
                    return
            except:
                continue
    except:
        pass
    
    # Strategy 5: Find element containing text, then click parent if needed
    try:
        locator = page.locator(f"text=/{text}/i").first
        is_visible = await locator.is_visible()
        if not is_visible:
            parent = locator.locator('..')
            await parent.scroll_into_view_if_needed(timeout=3000)
            await parent.click(timeout=5000)
            return
        else:
            await locator.scroll_into_view_if_needed(timeout=3000)
            await locator.click(timeout=5000)
            return
    except:
        pass
    
    # Strategy 6: Try clicking by role if it's a button or link
    try:
        locator = page.get_by_role('button', name=re.compile(text, re.IGNORECASE)).first
        await locator.scroll_into_view_if_needed(timeout=3000)
        await locator.click(timeout=5000)
        return
    except:
        pass
    
    # If all strategies fail, raise exception
    raise Exception(f"Could not click text '{text}' with any strategy")


async def click_symbol_element(page, symbol, context_keywords=None, get_url_state=None, intended_button_text=None):
    """Helper method to click symbol/icon elements (like +, ×, etc.).
    
    Args:
        page: Playwright page object
        symbol: The symbol to click (e.g., '+', '×')
        context_keywords: Optional list of keywords to help identify the right button
        get_url_state: Optional function to get URL state for context inference
        intended_button_text: Optional full intended button text (e.g., "Add view" when looking for "+ Add view")
    """
    # Extract context from page if not provided
    if context_keywords is None:
        context_keywords = []
        try:
            # Use URL state for more accurate context inference
            if get_url_state:
                url_state = await get_url_state()
                page_text = await page.locator('body').inner_text()
                page_text_lower = page_text.lower()
                
                # Use URL state flags (more reliable than string matching)
                if url_state.get('is_issue'):
                    context_keywords.append('issue')
                if url_state.get('is_project'):
                    context_keywords.append('project')
                if url_state.get('is_view'):
                    context_keywords.append('view')
                
                # Fallback to text matching if URL state doesn't provide context
                if not context_keywords:
                    if 'issue' in url_state.get('url', '') or 'issue' in page_text_lower:
                        context_keywords.append('issue')
                    if 'project' in url_state.get('url', '') or 'project' in page_text_lower:
                        context_keywords.append('project')
                    if 'task' in url_state.get('url', '') or 'task' in page_text_lower:
                        context_keywords.append('task')
        except:
            pass
    
    # Strategy 1: For any symbol with context, prioritize buttons matching context
    if context_keywords or intended_button_text:
        try:
            all_buttons = page.locator('button:visible, [role="button"]:visible, a:visible')
            scored_buttons = []
            
            # Normalize intended button text for matching
            intended_text_normalized = None
            if intended_button_text:
                intended_text_normalized = intended_button_text.strip().lower()
                # Extract words from intended text for better matching
                intended_words = set(re.findall(r'\b\w+\b', intended_text_normalized))
            
            for i in range(await all_buttons.count()):
                button = all_buttons.nth(i)
                try:
                    if not await button.is_visible():
                        continue
                        
                    button_text = await button.inner_text()
                    aria_label = await button.get_attribute('aria-label') or ''
                    title = await button.get_attribute('title') or ''
                    combined_text = (button_text + ' ' + aria_label + ' ' + title).lower()
                    combined_text_normalized = combined_text.strip()
                    
                    # Check if button contains the symbol
                    has_symbol = symbol in button_text or symbol in aria_label or symbol in title
                    if not has_symbol:
                        continue
                    
                    # Score the button based on context relevance
                    score = 0
                    
                    # Highest priority: Match against intended button text (exact or close match)
                    if intended_text_normalized:
                        # Exact match gets highest score
                        if intended_text_normalized in combined_text_normalized:
                            score += 50
                        # Check how many intended words are present
                        button_words = set(re.findall(r'\b\w+\b', combined_text_normalized))
                        matching_words = intended_words.intersection(button_words)
                        if matching_words:
                            # Score based on percentage of matching words
                            match_ratio = len(matching_words) / len(intended_words) if intended_words else 0
                            score += int(match_ratio * 30)
                    
                    # High score if button text contains context keywords
                    if context_keywords:
                        for keyword in context_keywords:
                            if keyword in combined_text_normalized:
                                score += 10
                    
                    # Check if button is in main content area (not sidebar)
                    try:
                        bounding_box = await button.bounding_box()
                        if bounding_box:
                            # Prefer buttons in the right half of the page (main content area)
                            page_width = page.viewport_size['width'] if page.viewport_size else 1920
                            if bounding_box['x'] > page_width * 0.3:  # Not in left sidebar
                                score += 5
                    except:
                        pass
                    
                    # Prefer buttons with create/add keywords (but only if they match context)
                    create_keywords = ['add', 'create', 'new']
                    for keyword in create_keywords:
                        if keyword in combined_text_normalized:
                            # Only boost if context matches or no specific context
                            if not context_keywords or any(ctx in combined_text_normalized for ctx in context_keywords):
                                score += 3
                    
                    # Penalize buttons with conflicting keywords ONLY if they don't match context
                    # Don't penalize words that are actually in the context (e.g., "view" when looking for "Add view")
                    if context_keywords:
                        conflicting_keywords = ['team', 'workspace', 'settings', 'profile', 'account', 'preferences']
                        for keyword in conflicting_keywords:
                            if keyword in combined_text_normalized:
                                # Only penalize if this keyword is NOT in context
                                if keyword not in [ctx.lower() for ctx in context_keywords]:
                                    score -= 5
                    
                    if score > 0:
                        scored_buttons.append((score, button, button_text.strip()))
                except:
                    continue
            
            # Sort by score (highest first) and try clicking the best match
            if scored_buttons:
                scored_buttons.sort(key=lambda x: x[0], reverse=True)
                # Log top candidates for debugging
                if len(scored_buttons) > 1:
                    top_candidates = scored_buttons[:3]
                    print(f"  Found {len(scored_buttons)} buttons with symbol '{symbol}', top candidates:")
                    for idx, (score, _, text) in enumerate(top_candidates, 1):
                        print(f"    {idx}. Score {score}: '{text[:60]}'")
                
                for score, button, text in scored_buttons:
                    try:
                        await button.scroll_into_view_if_needed(timeout=3000)
                        await button.click(timeout=5000)
                        print(f"  Clicked context-aware symbol button (score: {score}): '{text[:50]}'")
                        return
                    except:
                        continue
        except:
            pass
    
    # Strategy 2: Try exact text match for the symbol
    try:
        locator = page.locator(f'text="{symbol}"').first
        await locator.scroll_into_view_if_needed(timeout=3000)
        await locator.wait_for(state='visible', timeout=3000)
        await locator.click(timeout=5000)
        print(f"  Clicked symbol: '{symbol}'")
        return
    except:
        pass
    
    # Strategy 3: Find buttons/elements containing the symbol in text
    try:
        all_elements = page.locator(f'button, [role="button"], a, [role="link"], [onclick]')
        count = await all_elements.count()
        for i in range(count):
            element = all_elements.nth(i)
            try:
                element_text = await element.inner_text()
                if symbol in element_text:
                    if await element.is_visible():
                        await element.scroll_into_view_if_needed(timeout=3000)
                        await element.wait_for(state='visible', timeout=3000)
                        await element.click(timeout=5000)
                        print(f"  Clicked element containing symbol '{symbol}': '{element_text.strip()}'")
                        return
            except:
                continue
    except:
        pass
    
    # Strategy 4: For "+" symbol, also look for buttons with create/add-related aria-labels
    if symbol == '+':
        try:
            create_labels = ['add', 'create', 'new', 'plus', 'insert']
            for label in create_labels:
                try:
                    locator = page.locator(f'[aria-label*="{label}" i], [title*="{label}" i]').first
                    if await locator.count() > 0:
                        element = locator.first
                        if await element.is_visible():
                            tag_name = await element.evaluate('el => el.tagName.toLowerCase()')
                            role = await element.evaluate('el => el.getAttribute("role")')
                            if tag_name in ['button', 'a'] or role in ['button', 'link']:
                                await element.scroll_into_view_if_needed(timeout=3000)
                                await element.click(timeout=5000)
                                aria_label = await element.get_attribute('aria-label') or await element.get_attribute('title') or ''
                                print(f"  Clicked button with create/add label containing '{label}': '{aria_label}'")
                                return
                except:
                    continue
        except:
            pass
    
    # Strategy 5: Try aria-label or title containing the symbol
    try:
        locator = page.locator(f'[aria-label*="{symbol}"], [title*="{symbol}"]').first
        if await locator.count() > 0 and await locator.is_visible():
            await locator.scroll_into_view_if_needed(timeout=3000)
            await locator.click(timeout=5000)
            print(f"  Clicked element with aria-label/title containing '{symbol}'")
            return
    except:
        pass
    
    # Strategy 6: For "+" symbol, look for buttons that are likely create/add buttons
    if symbol == '+':
        try:
            all_buttons = page.locator('button:visible, [role="button"]:visible')
            count = await all_buttons.count()
            for i in range(count):
                button = all_buttons.nth(i)
                try:
                    button_text = await button.inner_text()
                    aria_label = await button.get_attribute('aria-label') or ''
                    title = await button.get_attribute('title') or ''
                    combined_text = (button_text + ' ' + aria_label + ' ' + title).lower()
                    
                    create_keywords = ['add', 'create', 'new', 'plus', '+', 'insert']
                    if any(keyword in combined_text for keyword in create_keywords):
                        if symbol in button_text or symbol in aria_label or symbol in title:
                            await button.scroll_into_view_if_needed(timeout=3000)
                            await button.click(timeout=5000)
                            print(f"  Clicked likely create/add button: '{button_text.strip() or aria_label or title}'")
                            return
                except:
                    continue
        except:
            pass
    
    # Strategy 7: Try finding by Unicode/character code or regex
    try:
        locator = page.locator(f'text=/{symbol}/').first
        await locator.scroll_into_view_if_needed(timeout=3000)
        await locator.wait_for(state='visible', timeout=3000)
        await locator.click(timeout=5000)
        print(f"  Clicked symbol using regex: '{symbol}'")
        return
    except:
        pass
    
    # Strategy 8: As a last resort, try keyboard shortcuts for common create/add actions
    if symbol == '+':
        try:
            shortcuts_to_try = ['c', 'n', 'a']
            for shortcut in shortcuts_to_try:
                try:
                    print(f"  Trying keyboard shortcut '{shortcut}' as fallback for create/add action...")
                    await page.keyboard.press(shortcut)
                    await page.wait_for_timeout(1000)
                    # Check if a form/modal appeared
                    try:
                        form_indicators = await page.locator('form, [role="dialog"], [role="modal"], input[type="text"]:visible, textarea:visible').count()
                        if form_indicators > 0:
                            print(f"  Keyboard shortcut '{shortcut}' successfully triggered create/add action")
                            return
                    except:
                        pass
                except:
                    continue
        except:
            pass
    
    # If all strategies fail, raise exception
    raise Exception(f"Could not click symbol '{symbol}' with any strategy")

