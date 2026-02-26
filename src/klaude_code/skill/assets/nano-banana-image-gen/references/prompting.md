# Prompting best practices (Gemini Image Generation)

## Core principle
**Describe the scene, don't just list keywords.** The model's core strength is deep language understanding. A narrative, descriptive paragraph produces better, more coherent images than disconnected keywords.

## Contents
- [Structure & specificity](#structure--specificity)
- [Photorealistic scenes](#photorealistic-scenes)
- [Stylized illustrations & stickers](#stylized-illustrations--stickers)
- [Accurate text in images](#accurate-text-in-images)
- [Product mockups & commercial photography](#product-mockups--commercial-photography)
- [Minimalist & negative space design](#minimalist--negative-space-design)
- [Sequential art & storyboards](#sequential-art--storyboards)
- [Search-grounded generation](#search-grounded-generation)
- [Editing strategies](#editing-strategies)
- [Avoiding tacky outputs](#avoiding-tacky-outputs)
- [Model-specific tips](#model-specific-tips)

## Structure & specificity
- Use a consistent order: scene/background -> subject -> key details -> constraints -> output intent.
- Include intended use (ad, UI mock, infographic) to set the mode and polish level.
- Name materials, textures, and visual medium (photo, watercolor, 3D render).
- For photorealism, include camera/composition language (lens, framing, lighting).

## Photorealistic scenes
Use photography terms: camera angles, lens types, lighting, fine details.

Template:
```
A photorealistic [shot type] of [subject], [action or expression], set in
[environment]. The scene is illuminated by [lighting description], creating
a [mood] atmosphere. Captured with a [camera/lens details], emphasizing
[key textures and details]. The image should be in a [aspect ratio] format.
```

Key tips:
- Mention specific lens (85mm portrait, 35mm wide, macro)
- Describe lighting precisely (golden hour, soft diffused, three-point)
- Call out textures (skin pores, fabric wear, wood grain)
- Specify mood (serene, dramatic, intimate)

## Stylized illustrations & stickers
Be explicit about style and request appropriate background.

Template:
```
A [style] sticker of a [subject], featuring [key characteristics] and a
[color palette]. The design should have [line style] and [shading style].
The background must be [transparent/white].
```

Key tips:
- Name the style explicitly (kawaii, flat vector, cel-shaded, watercolor)
- Specify outline style (bold clean outlines, no outlines, sketchy)
- Request white or transparent background for assets

## Accurate text in images
Use `gemini-3-pro-image-preview` for best text rendering results.

Template:
```
Create a [image type] for [brand/concept] with the text "[text to render]"
in a [font style]. The design should be [style description], with a
[color scheme].
```

Key tips:
- Put literal text in quotes
- Describe font style descriptively (bold sans-serif, elegant serif, handwritten)
- Spell uncommon words letter-by-letter if accuracy matters
- For best results, generate the text content first, then ask the model to create the image containing it

## Product mockups & commercial photography
Template:
```
A high-resolution, studio-lit product photograph of a [product description]
on a [background surface]. The lighting is a [lighting setup] to
[lighting purpose]. The camera angle is a [angle type] to showcase
[specific feature]. Ultra-realistic, with sharp focus on [key detail].
[Aspect ratio].
```

Key tips:
- Describe product materials precisely (matte black ceramic, brushed aluminum)
- Specify lighting setup (softbox, natural window light, rim lighting)
- Call out hero detail (steam rising, label clarity, texture closeup)

## Minimalist & negative space design
Template:
```
A minimalist composition featuring a single [subject] positioned in the
[bottom-right/top-left/etc.] of the frame. The background is a vast, empty
[color] canvas, creating significant negative space. Soft, subtle lighting.
[Aspect ratio].
```

Key tips:
- Specify where to leave space for text overlay
- Keep subject simple and singular
- Use soft, diffused lighting

## Sequential art & storyboards
For step-by-step visual guides or comics:
- Define each panel or step clearly
- Keep character descriptions consistent across panels
- Request interleaved text and image output (default `TEXT,IMAGE` modality)

## Search-grounded generation
Use `gemini-3-pro-image-preview` with `tools=[{"google_search": {}}]`.
- Describe what real-time data to visualize (weather forecast, recent event, stock data)
- The model fetches current information and incorporates it into the image
- Image-based search results are NOT passed to the model (text-only grounding)

## Editing strategies
- For edits, explicitly state invariants: "change only X; keep Y unchanged"
- Reference input images by role: "Image 1: product photo, Image 2: style reference"
- For multi-image composition, specify what moves where and matching requirements (lighting, perspective, scale)
- Repeat invariants on every iteration to reduce drift
- Use multi-turn chat for iterative editing (recommended by Google)

## Avoiding tacky outputs
- Avoid buzzwords: "epic", "cinematic", "trending", "8k", "award-winning", "unreal engine"
- Specify restraint: "minimal", "editorial", "premium", "subtle", "natural color grading"
- Add a negative line: "Avoid: stock-photo vibe; cheesy lens flare; oversaturated neon; harsh bloom; clutter"
- For 3D/illustration: name the finish ("matte", "paper grain", "ink texture", "flat color with soft shadow")

## Model-specific tips
### Flash (gemini-2.5-flash-image)
- Optimized for speed; great for iteration and high-volume tasks
- Best with simple to moderate prompts
- Use for quick prototyping before switching to Pro for final output

### Pro (gemini-3-pro-image-preview)
- Thinking mode produces better results for complex prompts (adds latency)
- Superior text rendering; use for any text-heavy output
- 4K output available; specify `image_size="4K"` for print-quality assets
- Google Search grounding for real-time data visualization
- Up to 14 reference images for complex composition

## Where to find copy/paste recipes
For ready-to-use prompt specs, see `references/sample-prompts.md`.
