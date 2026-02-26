# Sample prompts (copy/paste)

Use these as starting points. Keep user-provided requirements; do not invent new creative elements.
For prompting principles, see `references/prompting.md`.

## Generate

### photorealistic-scene
```
Use case: photorealistic-scene
Primary request: close-up portrait of an elderly Japanese ceramicist inspecting a freshly glazed tea bowl
Scene/background: rustic, sun-drenched workshop with pottery wheels and shelves
Subject: weathered face with sun-etched wrinkles, warm knowing smile
Style/medium: photorealistic candid photo
Composition/framing: close-up portrait, 85mm lens, soft blurred background
Lighting/mood: soft golden hour light streaming through a window
Constraints: natural color balance; no heavy retouching; no watermark
Avoid: studio polish; staged look
```

### product-mockup
```
Use case: product-mockup
Primary request: studio product photograph of a minimalist ceramic coffee mug in matte black
Scene/background: polished concrete surface, clean studio gradient
Subject: single mug centered with steam rising
Style/medium: premium product photography
Composition/framing: slightly elevated 45-degree shot, generous padding
Lighting/mood: three-point softbox setup, soft diffused highlights
Constraints: no logos or trademarks; no watermark; sharp focus on steam
```

### ui-mockup
```
Use case: ui-mockup
Primary request: mobile app UI for a local farmers market
Scene/background: clean white background
Subject: header, vendor list with photos, "Today's specials" section, location and hours
Style/medium: realistic product UI, not concept art
Composition/framing: iPhone frame, balanced spacing and hierarchy
Constraints: practical layout; clear typography; no watermark
```

### infographic-diagram
```
Use case: infographic-diagram
Primary request: vibrant infographic explaining photosynthesis as a recipe
Scene/background: colorful cookbook page style
Subject: ingredients (sunlight, water, CO2) and finished dish (sugar/energy)
Style/medium: kids' cookbook illustration, colorful and clear
Text (verbatim): "Sunlight", "Water", "CO2", "Sugar", "Energy"
Constraints: clear labels; strong contrast; suitable for 4th grader
```

### logo-brand
```
Use case: logo-brand
Primary request: modern minimalist logo for a coffee shop called "The Daily Grind"
Style/medium: vector logo mark; flat colors; minimal; black and white
Composition/framing: centered mark in a circle; clear silhouette
Text (verbatim): "The Daily Grind"
Constraints: clean bold sans-serif font; use coffee bean cleverly; no gradients; no watermark
```

### illustration-sticker
```
Use case: illustration-sticker
Primary request: kawaii-style sticker of a happy red panda wearing a tiny bamboo hat
Subject: red panda munching on a green bamboo leaf
Style/medium: kawaii sticker with bold clean outlines, simple cel-shading
Color palette: vibrant
Constraints: white background; no text; no watermark
```

### stylized-concept
```
Use case: stylized-concept
Primary request: perfectly isometric photo of a beautiful modern office interior
Style/medium: captured photo that happens to be perfectly isometric
Composition/framing: isometric perspective, not miniature
Lighting/mood: natural office lighting
Constraints: photorealistic; no tilt-shift; no watermark
```

### minimalist-negative-space
```
Use case: minimalist-negative-space
Primary request: single delicate red maple leaf on vast empty canvas
Composition/framing: leaf in bottom-right; significant negative space for text overlay
Lighting/mood: soft diffused lighting from top left
Color palette: off-white background, red accent
Constraints: no text; no clutter; square format
```

### search-grounded
```
Use case: search-grounded
Primary request: clear 45-degree top-down isometric miniature 3D cartoon scene of London with current weather
Style/medium: soft refined textures with realistic PBR materials, gentle lifelike lighting
Composition/framing: isometric miniature diorama, clean minimalistic, soft solid-colored background
Text (verbatim): "London" (title, large bold at top-center), weather icon, date (small), temperature (medium)
Constraints: centered text with consistent spacing; integrate real weather conditions
Note: requires --google-search flag and Pro model
```

## Edit

### style-transfer
```
Use case: style-transfer
Input images: Image 1: style reference
Primary request: apply Image 1's visual style to a man riding a motorcycle on a white background
Constraints: preserve palette, texture, and brushwork from reference; no extra elements; plain white background
```

### object-edit
```
Use case: object-edit
Input images: Image 1: room photo
Primary request: replace ONLY the white chairs with wooden chairs
Constraints: preserve camera angle, room lighting, floor shadows, and surrounding objects; keep all other aspects unchanged
```

### text-localization
```
Use case: text-localization
Input images: Image 1: original infographic
Primary request: translate all in-image text to Spanish
Constraints: change only the text; preserve layout, typography, spacing, and hierarchy; do not alter imagery
```

### multi-image-composition
```
Use case: multi-image-composition
Input images: Image 1-5: individual person photos
Primary request: an office group photo of these people making funny faces
Constraints: maintain each person's identity and appearance; natural office lighting; no extra people
```

### sketch-to-render
```
Use case: sketch-to-render
Input images: Image 1: pencil sketch
Primary request: turn this sketch into a photorealistic image
Constraints: preserve layout, proportions, and perspective; add plausible materials and lighting; no new elements or text
```

## Asset type templates

### Website hero
```
Use case: minimalist-negative-space
Asset type: landing page hero background
Primary request: minimal abstract background with soft gradient and subtle texture
Style/medium: matte illustration, soft-rendered (not glossy 3D)
Composition/framing: wide composition; large negative space on right for headline
Lighting/mood: gentle studio glow
Color palette: cool neutrals with restrained accent
Constraints: no text; no logos; no watermark
```

### Game environment concept
```
Use case: stylized-concept
Asset type: game environment concept art
Primary request: cavernous hangar interior with tall support beams and drifting fog
Scene/background: industrial hangar, deep scale, light haze
Subject: compact shuttle parked center-left, bay door open
Style/medium: cinematic concept art, industrial realism
Composition/framing: wide-angle, low-angle, cinematic framing
Lighting/mood: volumetric light rays cutting through fog
Constraints: no logos or trademarks; no watermark
```

### App icon
```
Use case: illustration-sticker
Asset type: app icon
Primary request: icon representing a cute dog
Style/medium: colorful tactile 3D style
Composition/framing: centered, generous padding, clear silhouette
Constraints: white background; no text; no watermark
```
