# agenius-media-public

Public media hosting for posts made by
[agenius-socialmedia-manager](https://github.com/thuglifeadem/agenius-socialmedia-manager).
Instagram downloads post images and videos from here, so this repo must stay public.
Only finished media belongs here: no drafts or secrets.

Layout: `<account>/<yyyy-mm>/<post-id>-<n>.jpg` for images, `<post-id>.mp4` for Reels.

## Reel encoding

Instagram needs H.264/AAC MP4 files. The bot renders an animation (WebM) or picks stock
footage, then pushes a `*.reel.json` spec. The **Encode reels** workflow
(`tools/encode.py`) turns each spec into an MP4 with ffmpeg and commits it next to the spec.
