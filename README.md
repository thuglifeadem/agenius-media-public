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

### Voice-over and music

A spec can carry an `audio` block. `voice.text` is spoken by
[edge-tts](https://github.com/rany2/edge-tts) (Microsoft neural voices, installed by the
workflow) and the video holds its last frame if the voice runs longer. `music` is either a
generated ambient bed (`{"mood": "calm"}` or `"bright"`, made with ffmpeg, so nothing to
license), a track in this repo (`{"path": ...}`), one picked from a folder
(`{"library": "music/calm"}`), or a Pixabay CDN link (`{"url": ...}`). The music ducks under
the voice. Without an `audio` block the Reel stays silent, as before.

Royalty-free tracks (for example from Pixabay Music) can be dropped into `music/<mood>/` and
used with `library`.
