# Framecraft Learnings — Improve Later

## HTML Scene Design

### Browser Mockup Patterns (from gTabs demo)
- **Tab groups need strong visual separation**: A colored label chip + colored bottom bar + tinted background per group. Without all three, groups blur into a flat row of pills.
- **Tab bar styling**: Use `display: flex` with each group as a flex item containing label + tabs. Group label should be a solid-colored chip (not tinted), tabs should be lightly tinted.
- **Chrome-accurate colors**: Traffic light dots (r/y/g), `#202124` title bar, `#292b2f` tab bar, `#35363a` URL input, rounded corners on everything.
- **Staggered entrance animations**: Groups should appear one-by-one with `0.4s` gaps. Use `cubic-bezier(0.16,1,0.3,1)` for spring-like motion.
- **Tab favicons**: Small colored squares (14px) with brand colors sell realism more than text alone.

### Layout Issues Discovered
- At 1920px width, a tab bar with 24 tabs gets cramped. Use fewer tabs per group (3-6) or allow horizontal scroll/compression.
- Group labels need `min-width` to stay readable when compressed.
- Content area height matters — too short and badges/text feel cramped.

### Animation Timing
- Title/headline: 0.2s delay, 0.7s duration
- Browser window: 0.1s delay (nearly instant)
- Tab groups: start at 0.5s, 0.4s gap between groups
- Content (checkmark, text, badges): start after last group lands (~2.7s)
- Total scene should be 4-6 seconds for comfortable viewing

## TTS / Voiceover

### edge-tts is the right default
- Microsoft neural voices (Andrew, Jenny, etc.) sound natural and professional
- Free, no API key, 10k+ GitHub stars, actively maintained
- Requires internet connection
- Fallback to macOS `say` when offline

### Voice recommendations for product demos
- **en-US-AndrewNeural**: Warm, professional male — best for product demos
- **en-US-JennyNeural**: Clear, friendly female — good alternative
- **en-US-DavisNeural**: Deeper male — good for dramatic/serious tone
- Avoid: Guy (too newscaster-y), Aria (too perky for product demos)

### Narration writing rules
- 1-2 sentences per scene, max ~20 words
- Lead with the benefit, not the feature name
- Use pauses (periods, commas) for natural pacing
- Avoid jargon — "your tabs organize themselves" > "AI-powered tab grouping"

## Scene Types to Add to Framecraft Later

### 1. `browser_mockup` built-in scene type
A reusable component that generates a Chrome-like browser window with:
- Configurable tab groups (name, color, tab list)
- Animated group entrance
- Optional URL bar content
- Optional content area (screenshot embed or custom HTML)

### 2. `zoom_focus` scene type
Takes a screenshot and zooms/pans to highlight a specific region:
- Start: full screenshot visible
- Animate: smooth zoom to region (CSS transform origin + scale)
- Highlight: dim everything outside the focus area

### 3. `callout_overlay` scene type
Adds positioned annotation labels with leader lines pointing to specific coordinates:
- Arrow/line from label to target point
- Staggered appearance with delays
- Color-coded by category

### 4. `split_comparison` scene type
Side-by-side before/after with a sliding divider:
- Left: "before" state
- Right: "after" state
- Divider slides from left to right

## Pipeline Issues

### Font loading
- Google Fonts `@import` works in Playwright but adds 200-500ms load time
- Consider bundling Inter font as a local file for offline/faster rendering
- Always add `page.wait_for_timeout(500)` after navigation for font load

### Frame rendering performance
- 30fps at 1920x1080 = ~150 screenshots per 5-second scene
- Each Playwright screenshot takes ~30-50ms
- Total render: ~2-3x real-time (5s scene = 10-15s render)
- Consider reducing to 24fps for faster renders with minimal quality loss

### ffmpeg crossfade
- `xfade` filter requires careful offset calculation
- Offset = cumulative duration of previous scenes minus transition_duration * index
- Use `fade` transition type — `dissolve` and `wipeleft` can artifact on dark backgrounds

### Audio sync
- edge-tts generates audio at natural speaking pace — no control over exact duration
- Scene duration should be set to match narration length + 1s buffer
- If narration is shorter than scene, silence pads automatically via ffmpeg `-shortest`
- If narration is longer, it gets cut — always test TTS duration first

## Custom HTML vs Built-in Scenes
- Built-in scenes (title, screenshot, bullets) cover 60% of use cases
- Custom HTML (`custom_html` field) is the escape hatch for everything else
- Keep framecraft generic — project-specific scenes should live in the project repo, not in framecraft
- The gTabs browser mockup is a perfect example: lives in `gtabs/store-assets/demo-scenes/`, not in framecraft
