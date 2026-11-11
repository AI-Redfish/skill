# YouTube Channels, Metrics, and Captions

Verify channel identity from the visible channel name and canonical handle. A
user-supplied handle can 404 while search resolves a different official handle;
state the resolution rather than silently substituting it.

For earliest uploads, use the channel Videos surface and verify the explicit
`Oldest`/localized sort is active. Collect canonical video IDs and deduplicate
by ID. Preserve upload versus premiere date and snapshot time. Watch-page view
counts may be available even when public like/comment counts are absent; report
missing engagement metrics as unavailable instead of inferring them from other
controls or snippets.

For captions, first inspect the player/description for a transcript or caption
control. A loaded video is not evidence that captions exist. If the player says
captions are unavailable and no transcript/download UI is present, do not use a
different backend to obtain them. Do not label description text or an AI summary
as transcript quotes. Return short, clearly labelled paraphrases only when they
still help, and state that no subtitle artifact was produced.

Verify video/channel identity, requested ordering, unique IDs, every reported
metric's visible label, caption availability, and any downloaded file. For an exposed file URL, use `page.fetch` with file output and validate the
retained file before finishing; this connection does not emit Playwright
download events.
